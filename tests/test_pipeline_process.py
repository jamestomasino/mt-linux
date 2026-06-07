import asyncio
from datetime import UTC, datetime
from pathlib import Path

from mt_linux.config import AppConfig
from mt_linux.daemon import MeetingPipeline
from mt_linux.diarization.diarizer import DiarizationSegment
from mt_linux.models import Attendee, CalendarEvent, MeetingInfo, TranscriptSegment
from mt_linux.pipeline.job import JobStatus, PipelineJob
from mt_linux.pipeline.review_queue import ReviewQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore
from tests.helpers import write_test_wav


def test_pipeline_process_writes_output_and_review_queue(tmp_path: Path, monkeypatch):
    audio_path = write_test_wav(tmp_path / "input.wav", seconds=3)
    config = AppConfig()
    config.output.folder = str(tmp_path / "out")
    store = JobSnapshotStore(tmp_path / "jobs")
    pipeline = MeetingPipeline(config, store=store)
    pipeline.review_queue = ReviewQueue(tmp_path / "review_queue.json")
    job = PipelineJob(
        session_id="session-1",
        app_audio_path=audio_path,
        mic_audio_path=audio_path,
        imported_audio_path=audio_path,
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="import",
            start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
            title="Weekly Standup",
            calendar_event=CalendarEvent(
                event_id="event-1",
                title="Weekly Standup",
                start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                organizer="Alice Smith",
                attendees=[Attendee(name="Alice Smith", email="alice@example.com")],
            ),
        ),
    )

    monkeypatch.setattr(pipeline, "_transcribe", lambda _job: [TranscriptSegment(start=0.0, end=1.0, text="Hello")])
    monkeypatch.setattr(
        pipeline,
        "_diarize",
        lambda _job: [DiarizationSegment(start=0.0, end=1.0, speaker="SPEAKER_01")],
    )
    monkeypatch.setattr(pipeline, "_generate_protocol", lambda _job, _segments: "Summary text")
    monkeypatch.setattr("mt_linux.daemon.notify", lambda *args, **kwargs: None)

    asyncio.run(pipeline.process(job))

    assert job.status == JobStatus.COMPLETE
    output_files = list((tmp_path / "out").glob("*.md"))
    assert len(output_files) == 1
    content = output_files[0].read_text(encoding="utf-8")
    assert "Summary text" in content
    assert "SPEAKER_01" in content
    assert len(pipeline.review_queue.load()) == 1


def test_pipeline_process_uses_speaker_profiles_before_review(tmp_path: Path, monkeypatch):
    audio_path = write_test_wav(tmp_path / "input.wav", seconds=3)
    config = AppConfig()
    config.output.folder = str(tmp_path / "out")
    store = JobSnapshotStore(tmp_path / "jobs")
    pipeline = MeetingPipeline(config, store=store)
    pipeline.review_queue = ReviewQueue(tmp_path / "review_queue.json")
    job = PipelineJob(
        session_id="session-2",
        app_audio_path=audio_path,
        mic_audio_path=audio_path,
        imported_audio_path=audio_path,
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="import",
            start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
            title="Weekly Standup",
        ),
    )

    class _FakeMatcher:
        def embed_wav(self, wav_path):
            return [1.0, 0.0]

        def match_embedding(self, embedding):
            return ("Alice Smith", 0.93)

        def update_profile(self, name, embedding):
            return None

    monkeypatch.setattr(pipeline, "_transcribe", lambda _job: [TranscriptSegment(start=0.0, end=1.0, text="Hello")])
    monkeypatch.setattr(
        pipeline,
        "_diarize",
        lambda _job: [DiarizationSegment(start=0.0, end=1.0, speaker="SPEAKER_01")],
    )
    monkeypatch.setattr(pipeline, "_generate_protocol", lambda _job, _segments: "Summary text")
    monkeypatch.setattr(pipeline, "_get_speaker_matcher", lambda: _FakeMatcher())
    monkeypatch.setattr("mt_linux.daemon.notify", lambda *args, **kwargs: None)

    asyncio.run(pipeline.process(job))

    output_files = list((tmp_path / "out").glob("*.md"))
    assert len(output_files) == 1
    content = output_files[0].read_text(encoding="utf-8")
    assert "[[Alice Smith]]" in content
    assert "voice_profile" in content
    assert pipeline.review_queue.load() == []


def test_pipeline_process_queues_ambiguous_meeting_review(tmp_path: Path, monkeypatch):
    audio_path = write_test_wav(tmp_path / "input.wav", seconds=3)
    config = AppConfig()
    config.output.folder = str(tmp_path / "out")
    store = JobSnapshotStore(tmp_path / "jobs")
    pipeline = MeetingPipeline(config, store=store)
    pipeline.review_queue = ReviewQueue(tmp_path / "review_queue.json")
    from mt_linux.pipeline.meeting_review_queue import MeetingReviewQueue

    pipeline.meeting_review_queue = MeetingReviewQueue(tmp_path / "meeting_review_queue.json")
    job = PipelineJob(
        session_id="session-3",
        app_audio_path=audio_path,
        mic_audio_path=audio_path,
        imported_audio_path=audio_path,
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="import",
            start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
            title="Weekly Standup",
            calendar_event=CalendarEvent(
                event_id="event-1",
                title="Weekly Standup",
                start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                conferencing_url="https://princeton.zoom.us/j/123",
                conferencing_type="zoom",
                response_status="accepted",
            ),
            calendar_candidates=[
                CalendarEvent(
                    event_id="event-1",
                    title="Weekly Standup",
                    start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                    end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                    conferencing_url="https://princeton.zoom.us/j/123",
                    conferencing_type="zoom",
                    response_status="accepted",
                ),
                CalendarEvent(
                    event_id="event-2",
                    title="Customer Call",
                    start_time=datetime(2026, 6, 7, 14, 31, tzinfo=UTC),
                    end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                    conferencing_url="https://princeton.zoom.us/j/456",
                    conferencing_type="zoom",
                    response_status="accepted",
                ),
            ],
            calendar_match_confidence="ambiguous",
            calendar_review_queued=True,
        ),
    )
    monkeypatch.setattr(pipeline, "_transcribe", lambda _job: [TranscriptSegment(start=0.0, end=1.0, text="Hello")])
    monkeypatch.setattr(pipeline, "_diarize", lambda _job: [])
    monkeypatch.setattr(pipeline, "_generate_protocol", lambda _job, _segments: "Summary text")
    monkeypatch.setattr("mt_linux.daemon.notify", lambda *args, **kwargs: None)

    asyncio.run(pipeline.process(job))
    entries = pipeline.meeting_review_queue.load()
    assert len(entries) == 1
    assert entries[0].selected_event_id == "event-1"
    assert entries[0].app == "zoom"
    assert entries[0].transcript_preview == ["SPEAKER_00: Hello"]
