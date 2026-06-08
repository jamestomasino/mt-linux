from datetime import datetime
from pathlib import Path

from mt_linux.models import MeetingInfo, ReviewEntry
from mt_linux.pipeline.job import PipelineJob
from mt_linux.pipeline.job_admin import remove_job
from mt_linux.pipeline.meeting_review_queue import MeetingReviewQueue
from mt_linux.pipeline.review_queue import ReviewQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore
from tests.helpers import write_test_wav


def test_remove_job_removes_snapshot_and_related_review_entries(tmp_path: Path):
    store = JobSnapshotStore(tmp_path / "jobs")
    review_queue = ReviewQueue(tmp_path / "review_queue.json")
    meeting_review_queue = MeetingReviewQueue(tmp_path / "meeting_review_queue.json")
    audio_path = write_test_wav(tmp_path / "audio" / "app.wav", seconds=1)
    mic_path = write_test_wav(tmp_path / "audio" / "mic.wav", seconds=1)
    job = PipelineJob(
        session_id="session-1",
        app_audio_path=audio_path,
        mic_audio_path=mic_path,
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 8, 12, 0),
        ),
    )
    store.save(job)
    sample_path = write_test_wav(tmp_path / "review-samples" / "session-1_SPEAKER_00.wav", seconds=1)
    review_queue.add(
        ReviewEntry(
            session_id="session-1",
            speaker_label="SPEAKER_00",
            sample_path=sample_path,
            calendar_attendees=[],
            meeting_title="Test",
            meeting_date=datetime(2026, 6, 8).date(),
            transcript_path=tmp_path / "meeting.md",
        )
    )

    removed, deleted_paths = remove_job(
        "session-1",
        delete_audio=False,
        review_queue=review_queue,
        meeting_review_queue=meeting_review_queue,
        store=store,
    )

    assert removed is True
    assert store.load_one("session-1") is None
    assert review_queue.load() == []
    assert sample_path in deleted_paths
    assert not sample_path.exists()


def test_remove_job_can_delete_audio_files(tmp_path: Path):
    store = JobSnapshotStore(tmp_path / "jobs")
    review_queue = ReviewQueue(tmp_path / "review_queue.json")
    meeting_review_queue = MeetingReviewQueue(tmp_path / "meeting_review_queue.json")
    app_audio = write_test_wav(tmp_path / "audio" / "app.wav", seconds=1)
    mic_audio = write_test_wav(tmp_path / "audio" / "mic.wav", seconds=1)
    mixed_audio = tmp_path / "audio" / "session-2_mix.wav"
    write_test_wav(mixed_audio, seconds=1)
    job = PipelineJob(
        session_id="session-2",
        app_audio_path=app_audio,
        mic_audio_path=mic_audio,
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 8, 12, 0),
        ),
    )
    store.save(job)

    removed, deleted_paths = remove_job(
        "session-2",
        delete_audio=True,
        review_queue=review_queue,
        meeting_review_queue=meeting_review_queue,
        store=store,
    )

    assert removed is True
    assert app_audio in deleted_paths
    assert mic_audio in deleted_paths
    assert mixed_audio in deleted_paths
    assert not app_audio.exists()
    assert not mic_audio.exists()
    assert not mixed_audio.exists()
