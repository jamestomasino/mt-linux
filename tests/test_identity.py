from datetime import UTC, datetime
from pathlib import Path

from mt_linux.config import AppConfig
from mt_linux.diarization.diarizer import DiarizationSegment
from mt_linux.models import Attendee, CalendarEvent, MeetingInfo, TranscriptSegment
from mt_linux.pipeline.identity import resolve_identities
from mt_linux.pipeline.job import PipelineJob
from mt_linux.pipeline.review_queue import ReviewQueue
from tests.helpers import write_test_wav


class _FakeMatcher:
    def __init__(self):
        self.updated = []

    def embed_wav(self, wav_path: Path):
        return [1.0, 0.0]

    def match_embedding(self, embedding):
        return ("Alice Smith", 0.91)

    def update_profile(self, name: str, embedding) -> None:
        self.updated.append((name, embedding))


def test_resolve_identities_creates_review_entries_for_unknown_speakers(tmp_path: Path):
    from mt_linux.pipeline import identity as identity_module

    identity_module.REVIEW_SAMPLES_DIR = tmp_path / "review-samples"
    audio_path = write_test_wav(tmp_path / "input.wav", seconds=4)
    transcript_path = tmp_path / "meeting.md"
    config = AppConfig()
    queue = ReviewQueue(tmp_path / "review_queue.json")
    job = PipelineJob(
        session_id="session-1",
        app_audio_path=audio_path,
        mic_audio_path=audio_path,
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
    identities = resolve_identities(
        config,
        [TranscriptSegment(start=0.0, end=1.5, text="Hello", speaker="SPEAKER_01", track="app")],
        [DiarizationSegment(start=0.0, end=1.5, speaker="SPEAKER_01")],
        transcript_path=transcript_path,
        review_queue=queue,
        job=job,
        source_audio_path=audio_path,
    )
    assert identities[0].review_queued is True
    entries = queue.load()
    assert len(entries) == 1
    assert entries[0].speaker_label == "SPEAKER_01"
    assert entries[0].sample_path.exists()
    assert entries[0].sample_path.parent == tmp_path / "review-samples"
    assert entries[0].sample_path.parent != transcript_path.parent
    assert entries[0].calendar_attendees == ["Alice Smith <alice@example.com>"]


def test_resolve_identities_uses_voice_profile_match_and_skips_review(tmp_path: Path):
    from mt_linux.pipeline import identity as identity_module

    identity_module.REVIEW_SAMPLES_DIR = tmp_path / "review-samples"
    audio_path = write_test_wav(tmp_path / "input.wav", seconds=4)
    transcript_path = tmp_path / "meeting.md"
    config = AppConfig()
    queue = ReviewQueue(tmp_path / "review_queue.json")
    matcher = _FakeMatcher()
    job = PipelineJob(
        session_id="session-2",
        app_audio_path=audio_path,
        mic_audio_path=audio_path,
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="import",
            start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
            title="Weekly Standup",
        ),
    )
    identities = resolve_identities(
        config,
        [TranscriptSegment(start=0.0, end=1.5, text="Hello", speaker="SPEAKER_01", track="app")],
        [DiarizationSegment(start=0.0, end=1.5, speaker="SPEAKER_01")],
        transcript_path=transcript_path,
        review_queue=queue,
        job=job,
        source_audio_path=audio_path,
        speaker_matcher=matcher,
    )
    assert identities[0].name == "Alice Smith"
    assert identities[0].confidence == "voice_profile"
    assert identities[0].review_queued is False
    assert identities[0].similarity == 0.91
    assert matcher.updated == [("Alice Smith", [1.0, 0.0])]
    assert queue.load() == []
    assert list((tmp_path / "review-samples").glob("*.wav")) == []
