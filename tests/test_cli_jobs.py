from datetime import datetime

from click.testing import CliRunner

from mt_linux.cli import cli
from mt_linux.config import AppConfig
from mt_linux.diarization.diarizer import DiarizationSegment
from mt_linux.models import SpeakerIdentity
from mt_linux.models import MeetingInfo, ReviewEntry
from mt_linux.pipeline.job import JobStatus, PipelineJob
from mt_linux.pipeline.meeting_review_queue import MeetingReviewQueue
from mt_linux.pipeline.review_queue import ReviewQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore
from tests.helpers import write_test_wav


def test_backfill_speaker_profiles_dry_run_counts_historical_matches(tmp_path, monkeypatch):
    store = JobSnapshotStore(tmp_path / "jobs")
    audio_path = write_test_wav(tmp_path / "audio" / "session-1_app.wav", seconds=2)
    job = PipelineJob(
        session_id="session-1",
        app_audio_path=audio_path,
        mic_audio_path=tmp_path / "audio" / "session-1_mic.wav",
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 8, 12, 0),
            title="Backfill Me",
        ),
        transcript_segments=[],
        app_transcript_segments=[],
        diarization_segments=[DiarizationSegment(start=0.0, end=1.0, speaker="SPEAKER_00")],
        identities=[SpeakerIdentity(label="SPEAKER_00", name="Alice Smith", confidence="manual_correction")],
    )
    store.save(job)

    class _FakeMatcher:
        def __init__(self, db_path, similarity_threshold):
            self.db = {}

    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: AppConfig())
    monkeypatch.setattr("mt_linux.cli.SpeakerMatcher", _FakeMatcher)
    runner = CliRunner()
    result = runner.invoke(cli, ["backfill-speaker-profiles", "--dry-run"])
    assert result.exit_code == 0
    assert "Would backfill 1 clip(s) across 1 job(s)." in result.output
    assert "New profiles discovered: 1" in result.output


def test_backfill_speaker_profiles_updates_matcher_from_historical_audio(tmp_path, monkeypatch):
    store = JobSnapshotStore(tmp_path / "jobs")
    app_audio = write_test_wav(tmp_path / "audio" / "session-1_app.wav", seconds=2)
    mic_audio = write_test_wav(tmp_path / "audio" / "session-1_mic.wav", seconds=2)
    mix_audio = tmp_path / "audio" / "session-1_mix.wav"
    write_test_wav(mix_audio, seconds=2)
    job = PipelineJob(
        session_id="session-1",
        app_audio_path=app_audio,
        mic_audio_path=mic_audio,
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 8, 12, 0),
            title="Backfill Me",
        ),
        transcript_segments=[],
        diarization_segments=[DiarizationSegment(start=0.0, end=1.0, speaker="SPEAKER_00")],
        identities=[SpeakerIdentity(label="SPEAKER_00", name="Alice Smith", confidence="voice_profile")],
    )
    store.save(job)
    updates: list[tuple[str, object]] = []

    class _FakeMatcher:
        def __init__(self, db_path, similarity_threshold):
            self.db = {}

        def embed_wav(self, wav_path):
            assert wav_path.exists()
            return [1.0, 0.0]

        def update_profile(self, name, embedding):
            updates.append((name, embedding))

    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: AppConfig())
    monkeypatch.setattr("mt_linux.cli.SpeakerMatcher", _FakeMatcher)
    runner = CliRunner()
    result = runner.invoke(cli, ["backfill-speaker-profiles"])
    assert result.exit_code == 0
    assert "Backfilled 1 clip(s) across 1 job(s)." in result.output
    assert updates == [("Alice Smith", [1.0, 0.0])]


def test_cli_jobs_lists_pending_and_failed_jobs(tmp_path, monkeypatch):
    store = JobSnapshotStore(tmp_path / "jobs")
    pending_job = PipelineJob(
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
    failed_job = PipelineJob(
        session_id="session-2",
        app_audio_path=tmp_path / "app2.wav",
        mic_audio_path=tmp_path / "mic2.wav",
        meeting_info=MeetingInfo(
            app="teams",
            pid=2,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 8, 13, 0),
            title="Needs Retry",
        ),
        status=JobStatus.FAILED,
        error="timeout",
    )
    completed_job = PipelineJob(
        session_id="session-3",
        app_audio_path=tmp_path / "app3.wav",
        mic_audio_path=tmp_path / "mic3.wav",
        meeting_info=MeetingInfo(
            app="meet",
            pid=3,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 8, 14, 0),
            title="Done",
        ),
        status=JobStatus.COMPLETE,
    )
    store.save(pending_job)
    store.save(failed_job)
    store.save(completed_job)
    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    runner = CliRunner()
    result = runner.invoke(cli, ["jobs"])
    assert result.exit_code == 0
    assert "session-1  pending  Catch-up" in result.output
    assert "session-2  failed  Needs Retry" in result.output
    assert "session-3  complete  Done" not in result.output


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


def test_cli_jobs_log_shows_recent_history(tmp_path, monkeypatch):
    store = JobSnapshotStore(tmp_path / "jobs")
    job = PipelineJob(
        session_id="session-3",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 8, 12, 0),
            title="Standup",
        ),
    )
    job.add_event("Transcription started")
    job.add_event("Summary refreshed after speaker review")
    store.save(job)
    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    runner = CliRunner()
    result = runner.invoke(cli, ["jobs", "log", "session-3"])
    assert result.exit_code == 0
    assert "session-3  pending  Standup" in result.output
    assert "Summary refreshed after speaker review" in result.output


def test_cli_jobs_retry_resets_failed_job_to_pending(tmp_path, monkeypatch):
    store = JobSnapshotStore(tmp_path / "jobs")
    review_queue = ReviewQueue(tmp_path / "review_queue.json")
    meeting_review_queue = MeetingReviewQueue(tmp_path / "meeting_review_queue.json")
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"wav")
    job = PipelineJob(
        session_id="session-4",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 8, 12, 0),
            title="Retry Me",
        ),
        status=JobStatus.FAILED,
        error="The read operation timed out",
        summary="Existing summary",
    )
    store.save(job)
    review_queue.add(
        ReviewEntry(
            session_id="session-4",
            speaker_label="SPEAKER_00",
            sample_path=sample,
            calendar_attendees=[],
            meeting_title="Retry Me",
            meeting_date=datetime(2026, 6, 8).date(),
            transcript_path=tmp_path / "missing.md",
        )
    )
    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    monkeypatch.setattr("mt_linux.cli.ReviewQueue", lambda: review_queue)
    monkeypatch.setattr("mt_linux.cli.MeetingReviewQueue", lambda: meeting_review_queue)
    runner = CliRunner()
    result = runner.invoke(cli, ["jobs", "retry", "session-4"])
    assert result.exit_code == 0
    assert "Retried session-4" in result.output
    updated = store.load_one("session-4")
    assert updated is not None
    assert updated.status == JobStatus.PENDING
    assert updated.error is None
    assert updated.summary == "Existing summary"
    assert review_queue.load() == []
    assert not sample.exists()
    assert updated.history[-1].status == "pending"
    assert updated.history[-1].message == "Retry requested"


def test_cli_jobs_retry_rejects_non_failed_job(tmp_path, monkeypatch):
    store = JobSnapshotStore(tmp_path / "jobs")
    job = PipelineJob(
        session_id="session-5",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 8, 12, 0),
            title="Still Running",
        ),
        status=JobStatus.TRANSCRIBED,
    )
    store.save(job)
    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    runner = CliRunner()
    result = runner.invoke(cli, ["jobs", "retry", "session-5"])
    assert result.exit_code == 1
    assert "Job is not failed: session-5" in result.output


def test_cli_tui_invokes_launcher(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr("mt_linux.cli._launch_tui", lambda: called.append("launched"))
    runner = CliRunner()
    result = runner.invoke(cli, ["tui"])
    assert result.exit_code == 0
    assert called == ["launched"]
