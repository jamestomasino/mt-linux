from datetime import datetime

from click.testing import CliRunner

from mt_linux.cli import cli
from mt_linux.models import MeetingInfo
from mt_linux.pipeline.job import PipelineJob
from mt_linux.pipeline.snapshot import JobSnapshotStore
from tests.helpers import write_test_wav


def test_cli_jobs_lists_pending_jobs(tmp_path, monkeypatch):
    store = JobSnapshotStore(tmp_path / "jobs")
    job = PipelineJob(
        session_id="session-1",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 8, 12, 0),
            title="Catch-up",
        ),
    )
    store.save(job)
    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    runner = CliRunner()
    result = runner.invoke(cli, ["jobs"])
    assert result.exit_code == 0
    assert "session-1  pending  Catch-up" in result.output


def test_cli_jobs_cancel_removes_job_and_audio(tmp_path, monkeypatch):
    store = JobSnapshotStore(tmp_path / "jobs")
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
    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    runner = CliRunner()
    result = runner.invoke(cli, ["jobs", "cancel", "--delete-audio", "session-2"])
    assert result.exit_code == 0
    assert "Canceled session-2 and deleted 3 file(s)" in result.output
    assert store.load_one("session-2") is None
