from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import logging
import os

# Ensure CUDA 12 compatibility libs are findable when system has CUDA 13
_CUDA_LIB_FIX = os.path.expanduser("~/.local/cuda-libs")
if os.path.isdir(_CUDA_LIB_FIX):
    _ld = os.environ.get("LD_LIBRARY_PATH", "")
    if _CUDA_LIB_FIX not in _ld:
        os.environ["LD_LIBRARY_PATH"] = f"{_CUDA_LIB_FIX}{':' if _ld else ''}{_ld}"

from mt_linux.audio.factory import create_session_recorder
from mt_linux.audio.wav import mix_wav_files, wav_duration_minutes, wav_files_identical
from mt_linux.config import AppConfig
from mt_linux.control import ControlResult, clear_request, read_request
from mt_linux.detection.calendar_lookup import CalendarLookupService
from mt_linux.detection.meeting_detector import MeetingDetector
from mt_linux.detection.start_gate import CalendarCoupledStartGate
from mt_linux.diarization.diarizer import DiarizationSegment, PyannoteDiarizer
from mt_linux.diarization.speaker_matcher import SpeakerMatcher
from mt_linux.enrichment.service import enrich_note
from mt_linux.models import SpeakerIdentity
from mt_linux.models import TranscriptSegment
from mt_linux.notifications import notify
from mt_linux.output.markdown import (
    _compute_transcription_confidence,
    output_path_for,
    render_meeting_markdown,
)
from mt_linux.paths import STATE_FILE, ensure_directories
from mt_linux.pipeline.identity import assign_speakers_to_transcript, resolve_identities
from mt_linux.pipeline.job_admin import cleanup_completed_job_audio
from mt_linux.pipeline.job import JobStatus, PipelineJob
from mt_linux.pipeline.meeting_review_queue import MeetingReviewQueue
from mt_linux.pipeline.queue import PipelineQueue
from mt_linux.pipeline.review_queue import ReviewQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore
from mt_linux.pipeline.transcript_tracks import (
    MIC_SPEAKER_LABEL,
    REMOTE_SPEAKER_LABEL,
    merge_track_segments,
    relabel_segments,
)
from mt_linux.protocol.ollama_generator import OllamaProtocolGenerator
from mt_linux.protocol.quality import has_substantive_transcript
from mt_linux.runtime.meeting_sessions import MeetingSessionManager
from mt_linux.transcription.cleanup import suppress_low_signal_segments
from mt_linux.transcription.faster_whisper import FasterWhisperEngine
from mt_linux.transcription.runtime import gpu_ready


class MeetingPipeline:
    def __init__(self, config: AppConfig, store: JobSnapshotStore | None = None):
        self.config = config
        self.review_queue = ReviewQueue()
        self.meeting_review_queue = MeetingReviewQueue()
        self.store = store or JobSnapshotStore()
        self._speaker_matcher: SpeakerMatcher | None = None

    async def process(self, job: PipelineJob) -> None:
        audio_path = self._processing_audio_path(job)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file does not exist: {audio_path}")
        if job.transcript_segments is None:
            job.transcript_segments = await asyncio.to_thread(self._transcribe, job)
            job.set_status(JobStatus.TRANSCRIBED, "Transcription complete")
            self.store.save(job)
            return
        if job.diarization_segments is None:
            try:
                job.diarization_segments = await asyncio.to_thread(self._diarize, job)
            except Exception:
                logging.exception("Diarization failed for %s", job.session_id)
                job.diarization_segments = []
            job.set_status(JobStatus.DIARIZED, "Diarization complete")
            self.store.save(job)
            return
        if job.identities is None:
            transcript_segments = self._assign_transcript_speakers(job)
            job.transcript_segments = transcript_segments
            job.identities = await asyncio.to_thread(self._resolve_identities, job, transcript_segments)
            job.add_event("Speaker identities resolved")
            self.store.save(job)
            return
        transcript_segments = self._assign_named_speakers(job)
        job.transcript_segments = transcript_segments
        if job.summary is None:
            job.summary = await asyncio.to_thread(self._generate_protocol, job, transcript_segments)
            refined = await asyncio.to_thread(self._refine_calendar_match, job)
            if refined:
                job.add_event(refined)
            job.add_event("Protocol summary generated")
            self.store.save(job)
            return
        if job.enrichment is None:
            transcript_text = "\n".join(f"{segment.speaker}: {segment.text}" for segment in transcript_segments if segment.text.strip())
            job.enrichment = await asyncio.to_thread(
                enrich_note, job.summary or "", transcript_text, self.config
            )
            job.add_event("Note enrichment generated")
            self.store.save(job)
            return
        rendered = render_meeting_markdown(
            job,
            self.config,
            transcript_segments=transcript_segments,
            identities=job.identities or [],
            summary=job.summary or "",
            enrichment=job.enrichment,
            transcription_confidence=_compute_transcription_confidence(transcript_segments),
        )
        job.set_status(JobStatus.WRITING_OUTPUT, "Writing markdown output")
        self.store.save(job)
        rendered.path.write_text(rendered.content, encoding="utf-8")
        job.set_status(JobStatus.COMPLETE, "Processing complete")
        self.store.save(job)
        self._queue_meeting_review(job, rendered.path, transcript_segments, job.identities or [])
        if any(identity.review_queued for identity in (job.identities or [])):
            notify(
                "Meeting Transcriber",
                f"Unidentified speakers in '{job.meeting_info.title or job.meeting_info.app}'. Run mt-ctl review.",
            )
        if job.meeting_info.calendar_review_queued:
            notify(
                "Meeting Transcriber",
                f"Ambiguous calendar match for '{job.meeting_info.title or job.session_id}'. Run mt-ctl review-meetings.",
            )
        cleanup_completed_job_audio(
            job,
            keep_audio=self.config.output.keep_audio,
            review_queue=self.review_queue,
        )
        self._cleanup_gpu_resources()

    def _transcribe(self, job: PipelineJob) -> list[TranscriptSegment]:
        job.set_status(JobStatus.TRANSCRIBING, "Transcription started")
        self.store.save(job)
        if self.config.transcription.engine != "faster-whisper":
            return []
        try:
            engine = FasterWhisperEngine(self.config.transcription)
        except RuntimeError as exc:
            logging.error(
                "Transcription engine init failed for %s: %s",
                job.session_id,
                exc,
            )
            raise RuntimeError(f"Transcription engine unavailable for {job.session_id}: {exc}") from exc
        language = self.config.transcription.language or None
        if job.imported_audio_path is not None or wav_files_identical(job.app_audio_path, job.mic_audio_path):
            audio_path = self._processing_audio_path(job)
            job.app_transcript_segments = None
            job.mic_transcript_segments = None
            return relabel_segments(
                engine.transcribe(audio_path, language=language),
                speaker=self.config.speakers.mic_speaker_name or MIC_SPEAKER_LABEL,
                track="mixed",
            )
        job.app_transcript_segments = relabel_segments(
            engine.transcribe(job.app_audio_path, language=language),
            speaker=REMOTE_SPEAKER_LABEL,
            track="app",
        )
        job.mic_transcript_segments = relabel_segments(
            suppress_low_signal_segments(
                engine.transcribe(job.mic_audio_path, language=language),
                track="mic",
            ),
            speaker=self.config.speakers.mic_speaker_name or MIC_SPEAKER_LABEL,
            track="mic",
        )
        return merge_track_segments(job.mic_transcript_segments, job.app_transcript_segments)

    def _diarize(self, job: PipelineJob) -> list[DiarizationSegment]:
        job.set_status(JobStatus.DIARIZING, "Diarization started")
        self.store.save(job)
        if not self.config.diarization.enabled or not self.config.diarization.hf_token:
            return []
        audio_path = self._diarization_audio_path(job)
        try:
            num_speakers = self._estimate_num_speakers(job)
            diarizer = PyannoteDiarizer(
                self.config.diarization.hf_token,
                num_speakers=num_speakers,
            )
        except RuntimeError as exc:
            logging.error(
                "Diarization engine init failed for %s: %s",
                job.session_id,
                exc,
            )
            return []
        return diarizer.diarize(audio_path)

    def _estimate_num_speakers(self, job: PipelineJob) -> int | None:
        """Estimate speaker count from calendar attendees + mic speaker.

        Caps the estimate to avoid over-segmentation when a calendar event
        has many attendees who don't actually speak (e.g. distribution lists).
        """
        MAX_SPEAKER_ESTIMATE = 8
        event = job.meeting_info.calendar_event
        if event and event.attendees:
            unique = {a.name.strip().lower() for a in event.attendees if a.name.strip()}
            return min(max(len(unique) + 1, 2), MAX_SPEAKER_ESTIMATE)
        return None

    def _generate_protocol(self, job: PipelineJob, segments: list[TranscriptSegment]) -> str:
        job.set_status(JobStatus.GENERATING_PROTOCOL, "Protocol generation started")
        self.store.save(job)
        if not self.config.protocol.enabled:
            return ""
        if not has_substantive_transcript(segments):
            return "No substantive transcript captured - protocol generation skipped."
        transcript = "\n".join(f"{segment.speaker}: {segment.text}" for segment in segments if segment.text.strip())
        generator = OllamaProtocolGenerator(self.config.protocol)
        try:
            return generator.generate(transcript, job.meeting_info)
        except Exception:
            logging.exception("Protocol generation failed for %s", job.session_id)
            return ""

    def _refine_calendar_match(self, job: PipelineJob) -> str:
        if not job.summary or not self.config.openai.enabled:
            return ""
        if job.meeting_info.calendar_match_confidence == "matched":
            return ""
        service = CalendarLookupService(self.config.calendar, self.config.openai)
        previous_title = job.meeting_info.title
        previous_event_id = job.meeting_info.calendar_event.event_id if job.meeting_info.calendar_event else ""
        previous_confidence = job.meeting_info.calendar_match_confidence
        generic_title = not previous_title or previous_title.strip().lower() == job.meeting_info.app.strip().lower()
        info = job.meeting_info
        if generic_title:
            info.title = None
        updated = service.refine_with_summary(info, job.summary)
        if updated.calendar_match_confidence == "matched" and updated.calendar_event:
            if generic_title:
                updated.title = updated.calendar_event.title
            if (
                updated.calendar_event.event_id != previous_event_id
                or updated.calendar_match_confidence != previous_confidence
            ):
                return f"OpenAI summary match selected '{updated.calendar_event.title}'"
            return ""
        if updated.calendar_review_queued and (
            updated.calendar_match_method == "openai_summary"
            or updated.calendar_match_confidence != previous_confidence
        ):
            if updated.calendar_candidates:
                return f"OpenAI summary match queued review with {len(updated.calendar_candidates)} candidate(s)"
            return "OpenAI summary match queued review"
        return ""

    def _get_speaker_matcher(self) -> SpeakerMatcher:
        if self._speaker_matcher is None:
            self._speaker_matcher = SpeakerMatcher(
                self.config.resolve_path(self.config.speakers.db_path),
                similarity_threshold=self.config.speakers.similarity_threshold,
            )
        return self._speaker_matcher

    def _queue_meeting_review(self, job: PipelineJob, transcript_path, transcript_segments, identities) -> None:
        if not job.meeting_info.calendar_review_queued:
            return
        from mt_linux.models import MeetingReviewEntry

        audio_path = self._processing_audio_path(job)
        self.meeting_review_queue.add(
            MeetingReviewEntry(
                session_id=job.session_id,
                transcript_path=transcript_path,
                selected_event_id=job.meeting_info.calendar_event.event_id if job.meeting_info.calendar_event else "",
                candidates=job.meeting_info.calendar_candidates,
                meeting_title=job.meeting_info.title,
                meeting_date=job.meeting_info.start_time.date(),
                app=job.meeting_info.app,
                detected_start_time=job.meeting_info.start_time,
                recording_duration_minutes=wav_duration_minutes(audio_path),
                identified_speakers=sorted({identity.name for identity in identities if identity.name}),
                transcript_preview=[
                    f"{segment.speaker}: {segment.text.strip()}"
                    for segment in transcript_segments[:5]
                    if segment.text.strip()
                ],
            )
        )

    def _processing_audio_path(self, job: PipelineJob):
        if job.imported_audio_path is not None:
            return job.imported_audio_path
        if wav_files_identical(job.app_audio_path, job.mic_audio_path):
            return job.app_audio_path
        mixed_path = job.app_audio_path.with_name(f"{job.session_id}_mix.wav")
        if not mixed_path.exists():
            mix_wav_files(job.app_audio_path, job.mic_audio_path, mixed_path)
        return mixed_path

    def _diarization_audio_path(self, job: PipelineJob):
        if job.app_transcript_segments is not None:
            return job.app_audio_path
        return self._processing_audio_path(job)

    def _identity_audio_path(self, job: PipelineJob):
        if job.app_transcript_segments is not None:
            return job.app_audio_path
        return self._processing_audio_path(job)

    def _assign_transcript_speakers(self, job: PipelineJob) -> list[TranscriptSegment]:
        if job.app_transcript_segments is not None:
            app_segments = assign_speakers_to_transcript(
                job.app_transcript_segments,
                job.diarization_segments,
            )
            return merge_track_segments(job.mic_transcript_segments or [], app_segments)
        return assign_speakers_to_transcript(
            job.transcript_segments or [],
            job.diarization_segments,
        )

    def _resolve_identities(self, job: PipelineJob, transcript_segments: list[TranscriptSegment]) -> list[SpeakerIdentity]:
        transcript_path = output_path_for(job, self.config)
        return resolve_identities(
            self.config,
            transcript_segments,
            job.diarization_segments or [],
            transcript_path=transcript_path,
            review_queue=self.review_queue,
            job=job,
            source_audio_path=self._identity_audio_path(job),
            speaker_matcher=self._get_speaker_matcher(),
        )

    def _cleanup_gpu_resources(self) -> None:
        """Unload the ollama model and clear CUDA caches after a job completes.

        Prevents GPU memory from being held hostage by the local LLM, which
        would block other workloads (or the next mt-linux job).
        """
        if self.config.protocol.enabled:
            self._unload_ollama_model()
        self._clear_cuda_cache()

    def _unload_ollama_model(self) -> None:
        """Ask ollama to unload the currently loaded model from GPU memory."""
        if not self.config.protocol.enabled:
            return
        try:
            import subprocess
            subprocess.run(
                ["ollama", "stop", self.config.model],
                capture_output=True, timeout=10, check=False,
            )
            logging.info("Unloaded ollama model '%s'", self.config.model)
        except Exception:
            logging.debug("Failed to unload ollama model (non-fatal)")

    @staticmethod
    def _clear_cuda_cache() -> None:
        """Free cached GPU memory so the next job (or other processes) can use it."""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats()
        except Exception:
            pass

    def _assign_named_speakers(self, job: PipelineJob) -> list[TranscriptSegment]:
        assigned = self._assign_transcript_speakers(job)
        identity_map = {identity.label: identity.name for identity in (job.identities or [])}
        normalized: list[TranscriptSegment] = []
        for segment in assigned:
            normalized.append(
                TranscriptSegment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text,
                    speaker=identity_map.get(segment.speaker, segment.speaker),
                    confidence=segment.confidence,
                    track=segment.track,
                )
            )
        return normalized


class DaemonState:
    def __init__(self, queue: PipelineQueue, session_manager: MeetingSessionManager):
        self.queue = queue
        self.session_manager = session_manager
        self.last_control_result: ControlResult | None = None

    def write(self) -> None:
        ensure_directories()
        state = self.queue.snapshot()
        active = self.session_manager.active
        state["active_meeting"] = (
            {
                "session_id": active.capture_session.session_id,
                "title": active.meeting_info.title or active.meeting_info.app,
                "app": active.meeting_info.app,
                "detection_method": active.meeting_info.detection_method,
                "start_time": active.meeting_info.start_time.isoformat(),
            }
            if active is not None
            else None
        )
        state["last_control_result"] = (
            self.last_control_result.to_dict() if self.last_control_result is not None else None
        )
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)


class MeetingLifecycleCoordinator:
    def __init__(
        self,
        session_manager: MeetingSessionManager,
        state: DaemonState,
        *,
        handoff_window_seconds: int = 30,
    ):
        self.session_manager = session_manager
        self.state = state
        self.handoff_window = timedelta(seconds=handoff_window_seconds)
        self._last_ended_title: str | None = None
        self._last_ended_at: datetime | None = None

    async def handle_meeting_start(self, info) -> None:
        previous_title = self._recent_ended_title()
        await self.session_manager.handle_meeting_start(info)
        self.state.write()
        active = self.session_manager.active
        if active is None:
            return
        current_title = active.meeting_info.title or active.meeting_info.app
        if previous_title and previous_title != current_title:
            notify(
                "Meeting Transcriber",
                f"Meeting changed: {previous_title} -> {current_title}",
                urgency="critical",
            )

    async def handle_meeting_end(self, info) -> None:
        active = self.session_manager.active
        ended_title = None
        if active is not None:
            ended_title = active.meeting_info.title or active.meeting_info.app
        elif info.title or info.app:
            ended_title = info.title or info.app
        await self.session_manager.handle_meeting_end(info)
        if ended_title:
            self._last_ended_title = ended_title
            self._last_ended_at = datetime.now(UTC)
        self.state.write()

    def _recent_ended_title(self) -> str | None:
        if self._last_ended_title is None or self._last_ended_at is None:
            return None
        if datetime.now(UTC) - self._last_ended_at > self.handoff_window:
            self._last_ended_title = None
            self._last_ended_at = None
            return None
        return self._last_ended_title


async def handle_control_request(
    session_manager: MeetingSessionManager,
    state: DaemonState,
) -> bool:
    request = read_request()
    if request is None:
        return False
    try:
        if request.action == "start":
            active = await session_manager.start_manual_recording(
                title=request.title,
                app=request.app or "manual",
            )
            if active is None:
                state.last_control_result = ControlResult(
                    request_id=request.request_id,
                    status="error",
                    message="Another recording session is already active.",
                )
            else:
                state.last_control_result = ControlResult(
                    request_id=request.request_id,
                    status="ok",
                    message="Manual recording started.",
                    session_id=active.capture_session.session_id,
                )
        elif request.action == "stop":
            job = await session_manager.stop_manual_recording()
            if job is None:
                state.last_control_result = ControlResult(
                    request_id=request.request_id,
                    status="error",
                    message="No active manual recording to stop.",
                )
            else:
                state.last_control_result = ControlResult(
                    request_id=request.request_id,
                    status="ok",
                    message="Manual recording stopped and queued.",
                    session_id=job.session_id,
                )
        else:
            state.last_control_result = ControlResult(
                request_id=request.request_id,
                status="error",
                message=f"Unknown control action: {request.action}",
            )
    finally:
        clear_request()
    state.write()
    return True


def handle_job_failure(job: PipelineJob, exc: Exception) -> None:
    notify(
        "Meeting Transcriber",
        f"Job failed for '{job.meeting_info.title or job.session_id}': {exc}",
    )


async def run_daemon() -> None:
    logging.basicConfig(level=logging.INFO)
    config = AppConfig.load()
    store = JobSnapshotStore()
    queue = PipelineQueue(store=store)
    pipeline = MeetingPipeline(config, store=store)
    calendar_lookup = CalendarLookupService(config.calendar)
    start_gate = CalendarCoupledStartGate(calendar_lookup)
    session_manager = MeetingSessionManager(
        queue=queue,
        calendar_lookup=calendar_lookup,
        recorder=create_session_recorder(config.audio),
    )
    state = DaemonState(queue, session_manager)
    coordinator = MeetingLifecycleCoordinator(session_manager, state)
    await queue.restore()

    # Build GPU-ready check when deferral is enabled
    ready_check = None
    if config.pipeline.defer_on_gpu_busy:
        min_free = config.pipeline.gpu_min_free_mb
        ready_check = lambda: gpu_ready(min_free_mb=min_free)

    worker = asyncio.create_task(
        queue.run_worker(
            pipeline.process,
            on_failure=handle_job_failure,
            ready_check=ready_check,
            ready_poll_interval=config.pipeline.gpu_poll_interval_seconds,
        )
    )
    loop = asyncio.get_running_loop()
    detector = MeetingDetector(
        on_meeting_start=lambda info: asyncio.run_coroutine_threadsafe(
            coordinator.handle_meeting_start(info), loop
        ),
        on_meeting_end=lambda info: asyncio.run_coroutine_threadsafe(
            coordinator.handle_meeting_end(info), loop
        ),
        poll_interval=config.detection.poll_interval_seconds,
        grace_period_seconds=config.detection.grace_period_seconds,
        activity_gate=start_gate.allows,
    )
    detector.start()
    try:
        while True:
            await handle_control_request(session_manager, state)
            state.write()
            await asyncio.sleep(1)
    finally:
        detector.stop()
        worker.cancel()
