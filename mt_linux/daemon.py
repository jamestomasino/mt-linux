from __future__ import annotations

import asyncio
import json
import logging

from mt_linux.audio.factory import create_session_recorder
from mt_linux.audio.wav import mix_wav_files, wav_duration_minutes, wav_files_identical
from mt_linux.config import AppConfig
from mt_linux.control import ControlResult, clear_request, read_request
from mt_linux.detection.calendar_lookup import CalendarLookupService
from mt_linux.detection.meeting_detector import MeetingDetector
from mt_linux.detection.start_gate import CalendarCoupledStartGate
from mt_linux.diarization.diarizer import DiarizationSegment, PyannoteDiarizer
from mt_linux.diarization.speaker_matcher import SpeakerMatcher
from mt_linux.models import TranscriptSegment
from mt_linux.notifications import notify
from mt_linux.output.markdown import render_meeting_markdown
from mt_linux.paths import STATE_FILE, ensure_directories
from mt_linux.pipeline.identity import assign_speakers_to_transcript, resolve_identities
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
from mt_linux.transcription.faster_whisper import FasterWhisperEngine


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
            job.status = JobStatus.TRANSCRIBED
            self.store.save(job)
            return
        if job.diarization_segments is None:
            try:
                job.diarization_segments = await asyncio.to_thread(self._diarize, job)
            except Exception:
                logging.exception("Diarization failed for %s", job.session_id)
                job.diarization_segments = []
            job.status = JobStatus.DIARIZED
            self.store.save(job)
            return
        transcript_segments = self._assign_transcript_speakers(job)
        job.transcript_segments = transcript_segments
        if job.summary is None:
            job.summary = await asyncio.to_thread(self._generate_protocol, job, transcript_segments)
        rendered = render_meeting_markdown(
            job,
            self.config,
            transcript_segments=transcript_segments,
            identities=[],
            summary=job.summary or "",
        )
        identities = resolve_identities(
            self.config,
            transcript_segments,
            job.diarization_segments,
            transcript_path=rendered.path,
            review_queue=self.review_queue,
            job=job,
            source_audio_path=self._identity_audio_path(job),
            speaker_matcher=self._get_speaker_matcher(),
        )
        rendered = render_meeting_markdown(
            job,
            self.config,
            transcript_segments=transcript_segments,
            identities=identities,
            summary=job.summary or "",
        )
        job.status = JobStatus.WRITING_OUTPUT
        self.store.save(job)
        rendered.path.write_text(rendered.content, encoding="utf-8")
        job.status = JobStatus.COMPLETE
        self.store.save(job)
        self._queue_meeting_review(job, rendered.path, transcript_segments, identities)
        if any(identity.review_queued for identity in identities):
            notify(
                "Meeting Transcriber",
                f"Unidentified speakers in '{job.meeting_info.title or job.meeting_info.app}'. Run mt-ctl review.",
            )
        if job.meeting_info.calendar_review_queued:
            notify(
                "Meeting Transcriber",
                f"Ambiguous calendar match for '{job.meeting_info.title or job.session_id}'. Run mt-ctl review-meetings.",
            )

    def _transcribe(self, job: PipelineJob) -> list[TranscriptSegment]:
        job.status = JobStatus.TRANSCRIBING
        self.store.save(job)
        if self.config.transcription.engine != "faster-whisper":
            return []
        try:
            engine = FasterWhisperEngine(self.config.transcription)
        except RuntimeError:
            return []
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
            engine.transcribe(job.mic_audio_path, language=language),
            speaker=self.config.speakers.mic_speaker_name or MIC_SPEAKER_LABEL,
            track="mic",
        )
        return merge_track_segments(job.mic_transcript_segments, job.app_transcript_segments)

    def _diarize(self, job: PipelineJob) -> list[DiarizationSegment]:
        job.status = JobStatus.DIARIZING
        self.store.save(job)
        if not self.config.diarization.enabled or not self.config.diarization.hf_token:
            return []
        audio_path = self._diarization_audio_path(job)
        try:
            diarizer = PyannoteDiarizer(self.config.diarization.hf_token)
        except RuntimeError:
            return []
        return diarizer.diarize(audio_path)

    def _generate_protocol(self, job: PipelineJob, segments: list[TranscriptSegment]) -> str:
        job.status = JobStatus.GENERATING_PROTOCOL
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

    def _get_speaker_matcher(self) -> SpeakerMatcher:
        if self._speaker_matcher is None:
            self._speaker_matcher = SpeakerMatcher(
                self.config.resolve_path(self.config.speakers.db_path),
                similarity_threshold=self.config.speakers.similarity_threshold,
            )
        return self._speaker_matcher

    def _queue_meeting_review(self, job: PipelineJob, transcript_path, transcript_segments, identities) -> None:
        if not job.meeting_info.calendar_review_queued or not job.meeting_info.calendar_candidates:
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
    await queue.restore()
    worker = asyncio.create_task(queue.run_worker(pipeline.process, on_failure=handle_job_failure))
    loop = asyncio.get_running_loop()
    detector = MeetingDetector(
        on_meeting_start=lambda info: asyncio.run_coroutine_threadsafe(
            session_manager.handle_meeting_start(info), loop
        ),
        on_meeting_end=lambda info: asyncio.run_coroutine_threadsafe(
            session_manager.handle_meeting_end(info), loop
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
