from datetime import datetime
from pathlib import Path

from mt_linux.cleanup import cleanup_runtime_artifacts
from mt_linux.models import MeetingInfo, ReviewEntry
from mt_linux.pipeline.job import JobStatus, PipelineJob
from mt_linux.pipeline.review_queue import ReviewQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore
from tests.helpers import write_test_wav


def test_cleanup_removes_orphaned_audio_and_review_samples(tmp_path: Path, monkeypatch):
    from mt_linux import cleanup as cleanup_module

    monkeypatch.setattr(cleanup_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cleanup_module, "REVIEW_SAMPLES_DIR", tmp_path / "review-samples")

    store = JobSnapshotStore(tmp_path / "jobs")
    review_queue = ReviewQueue(tmp_path / "review_queue.json")
    tracked_app = write_test_wav(tmp_path / "audio" / "tracked_app.wav", seconds=1)
    tracked_mic = write_test_wav(tmp_path / "audio" / "tracked_mic.wav", seconds=1)
    orphan_audio = write_test_wav(tmp_path / "audio" / "orphan.wav", seconds=1)
    tracked_sample = write_test_wav(tmp_path / "review-samples" / "tracked.wav", seconds=1)
    orphan_sample = write_test_wav(tmp_path / "review-samples" / "orphan.wav", seconds=1)

    job = PipelineJob(
        session_id="session-1",
        app_audio_path=tracked_app,
        mic_audio_path=tracked_mic,
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 8, 12, 0),
        ),
    )
    store.save(job)
    review_queue.add(
        ReviewEntry(
            session_id="session-1",
            speaker_label="SPEAKER_00",
            sample_path=tracked_sample,
            calendar_attendees=[],
            meeting_title="Test",
            meeting_date=datetime(2026, 6, 8).date(),
            transcript_path=tmp_path / "meeting.md",
        )
    )

    result = cleanup_runtime_artifacts(store=store, review_queue=review_queue)

    assert orphan_audio in result.removed_paths
    assert orphan_sample in result.removed_paths
    assert tracked_app.exists()
    assert tracked_mic.exists()
    assert tracked_sample.exists()
    assert not orphan_audio.exists()
    assert not orphan_sample.exists()


def test_cleanup_can_remove_completed_job_history(tmp_path: Path, monkeypatch):
    from mt_linux import cleanup as cleanup_module

    monkeypatch.setattr(cleanup_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cleanup_module, "REVIEW_SAMPLES_DIR", tmp_path / "review-samples")

    store = JobSnapshotStore(tmp_path / "jobs")
    review_queue = ReviewQueue(tmp_path / "review_queue.json")
    app_audio = write_test_wav(tmp_path / "audio" / "app.wav", seconds=1)
    mic_audio = write_test_wav(tmp_path / "audio" / "mic.wav", seconds=1)
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
        status=JobStatus.COMPLETE,
    )
    store.save(job)

    result = cleanup_runtime_artifacts(
        store=store,
        review_queue=review_queue,
        include_job_history=True,
    )

    assert store.load_one("session-2") is None
    assert store.path_for("session-2") in result.removed_job_snapshots
    assert not app_audio.exists()
    assert not mic_audio.exists()
