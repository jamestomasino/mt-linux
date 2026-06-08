from datetime import datetime

from click.testing import CliRunner

from mt_linux.cli import cli
from mt_linux.models import MeetingInfo
from mt_linux.pipeline.job import PipelineJob, JobStatus
from mt_linux.pipeline.snapshot import JobSnapshotStore
from tests.helpers import write_test_wav


def test_cli_cleanup_dry_run_reports_orphans(tmp_path, monkeypatch):
    from mt_linux import cleanup as cleanup_module

    monkeypatch.setattr(cleanup_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cleanup_module, "REVIEW_SAMPLES_DIR", tmp_path / "review-samples")

    store = JobSnapshotStore(tmp_path / "jobs")
    write_test_wav(tmp_path / "audio" / "orphan.wav", seconds=1)
    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)

    runner = CliRunner()
    result = runner.invoke(cli, ["cleanup", "--dry-run"])
    assert result.exit_code == 0
    assert "Would remove artifact:" in result.output


def test_cli_cleanup_can_remove_completed_job_history(tmp_path, monkeypatch):
    from mt_linux import cleanup as cleanup_module

    monkeypatch.setattr(cleanup_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cleanup_module, "REVIEW_SAMPLES_DIR", tmp_path / "review-samples")

    store = JobSnapshotStore(tmp_path / "jobs")
    app_audio = write_test_wav(tmp_path / "audio" / "app.wav", seconds=1)
    mic_audio = write_test_wav(tmp_path / "audio" / "mic.wav", seconds=1)
    job = PipelineJob(
        session_id="session-1",
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
    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)

    runner = CliRunner()
    result = runner.invoke(cli, ["cleanup", "--include-job-history"])
    assert result.exit_code == 0
    assert "Removed job snapshot:" in result.output
    assert store.load_one("session-1") is None
