from __future__ import annotations

import asyncio
import json
import logging

from mt_linux.audio.factory import create_session_recorder
from mt_linux.audio.wav import wav_duration_minutes
from mt_linux.config import AppConfig
from mt_linux.detection.calendar_lookup import CalendarLookupService
from mt_linux.detection.meeting_detector import MeetingDetector
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
from mt_linux.protocol.ollama_generator import OllamaProtocolGenerator
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
        audio_path = job.imported_audio_path or job.app_audio_path
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file does not exist: {audio_path}")
        transcription_segments = await asyncio.to_thread(self._transcribe, job)
        diarization_segments = await asyncio.to_thread(self._diarize, job)
        transcript_segments = assign_speakers_to_transcript(transcription_segments, diarization_segments)
        summary = await asyncio.to_thread(self._generate_protocol, job, transcript_segments)
        rendered = render_meeting_markdown(
            job,
            self.config,
            transcript_segments=transcript_segments,
            identities=[],
            summary=summary,
        )
        identities = resolve_identities(
            self.config,
            diarization_segments,
            transcript_path=rendered.path,
            review_queue=self.review_queue,
            job=job,
            source_audio_path=job.imported_audio_path or job.app_audio_path,
            speaker_matcher=self._get_speaker_matcher(),
        )
        rendered = render_meeting_markdown(
            job,
            self.config,
            transcript_segments=transcript_segments,
            identities=identities,
            summary=summary,
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
        audio_path = job.imported_audio_path or job.app_audio_path
        if self.config.transcription.engine != "faster-whisper":
            return []
        try:
            engine = FasterWhisperEngine(self.config.transcription)
        except RuntimeError:
            return []
        return engine.transcribe(audio_path, language=self.config.transcription.language or None)

    def _diarize(self, job: PipelineJob) -> list[DiarizationSegment]:
        job.status = JobStatus.DIARIZING
        self.store.save(job)
        if not self.config.diarization.enabled or not self.config.diarization.hf_token:
            return []
        audio_path = job.imported_audio_path or job.app_audio_path
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
        transcript = "\n".join(segment.text for segment in segments)
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

        audio_path = job.imported_audio_path or job.app_audio_path
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


class DaemonState:
    def __init__(self, queue: PipelineQueue):
        self.queue = queue

    def write(self) -> None:
        ensure_directories()
        state = self.queue.snapshot()
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)


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
    state = DaemonState(queue)
    calendar_lookup = CalendarLookupService(config.calendar)
    session_manager = MeetingSessionManager(
        queue=queue,
        calendar_lookup=calendar_lookup,
        recorder=create_session_recorder(config.audio),
    )
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
    )
    detector.start()
    try:
        while True:
            state.write()
            await asyncio.sleep(5)
    finally:
        detector.stop()
        worker.cancel()
