from datetime import UTC, date, datetime
from pathlib import Path

from click.testing import CliRunner

from mt_linux.cli import cli
from mt_linux.config import AppConfig
from mt_linux.models import CalendarEvent, MeetingInfo, MeetingReviewEntry
from mt_linux.pipeline.job import JobStatus, PipelineJob
from mt_linux.pipeline.meeting_review_queue import MeetingReviewQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore
from tests.helpers import write_test_wav


def test_review_meetings_can_mark_session_as_external(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "2026-06-07_14-30_weekly-standup.md"
    transcript.write_text(
        """---
title: "Weekly Standup"
organizer: "[[Alice Smith]]"
calendar_event_id: "event-1"
calendar_match_confidence: "ambiguous"
calendar_review_queued: true
calendar_candidate_event_ids:
  - "event-1"
calendar_candidates:
  - id: "event-1"
    title: "Weekly Standup"
    conferencing: "zoom"
    response_status: "accepted"
---
""",
        encoding="utf-8",
    )
    queue = MeetingReviewQueue(tmp_path / "meeting_review_queue.json")
    monkeypatch.setattr("mt_linux.cli.MeetingReviewQueue", lambda: queue)
    queue.add(
        MeetingReviewEntry(
            session_id="session-1",
            transcript_path=transcript,
            selected_event_id="event-1",
            candidates=[
                CalendarEvent(
                    event_id="event-1",
                    title="Weekly Standup",
                    start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                    end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                    organizer="Alice Smith",
                    attendees=[],
                    conferencing_url="https://princeton.zoom.us/j/123",
                    conferencing_type="zoom",
                    response_status="accepted",
                )
            ],
            meeting_title="Weekly Standup",
            meeting_date=date(2026, 6, 7),
            app="zoom",
            detected_start_time=datetime(2026, 6, 7, 14, 31, tzinfo=UTC),
            recording_duration_minutes=45,
            identified_speakers=["Alice Smith"],
            transcript_preview=["SPEAKER_00: Hello there", "SPEAKER_01: Hi"],
        )
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["review-meetings", "run"],
        input="n\n\n",
        env={},
    )
    assert result.exit_code == 0
    assert "Detected: app=zoom start=2026-06-07T14:31:00+00:00 duration=45m" in result.output
    assert "Transcript preview:" in result.output
    assert "SPEAKER_00: Hello there" in result.output
    assert "organizer=Alice Smith" in result.output
    assert "link=princeton.zoom.us" in result.output
    assert "Marked as non-calendar / ad-hoc meeting" in result.output
    assert queue.load() == []
    renamed = tmp_path / "2026-06-07_14-30_weekly-standup.md"
    content = renamed.read_text(encoding="utf-8")
    assert 'calendar_match_confidence: "external"' in content


def test_review_meetings_rejects_invalid_selection(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
title: "Weekly Standup"
calendar_event_id: "event-1"
calendar_match_confidence: "ambiguous"
calendar_review_queued: true
calendar_candidate_event_ids:
  - "event-1"
calendar_attendees:
  - ""
calendar_candidates:
  - id: "event-1"
    title: "Weekly Standup"
    conferencing: "zoom"
    response_status: "accepted"
---
""",
        encoding="utf-8",
    )
    queue = MeetingReviewQueue(tmp_path / "meeting_review_queue.json")
    monkeypatch.setattr("mt_linux.cli.MeetingReviewQueue", lambda: queue)
    queue.add(
        MeetingReviewEntry(
            session_id="session-1",
            transcript_path=transcript,
            selected_event_id="event-1",
            candidates=[
                CalendarEvent(
                    event_id="event-1",
                    title="Weekly Standup",
                    start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                    end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                    conferencing_type="zoom",
                    response_status="accepted",
                )
            ],
            meeting_title="Weekly Standup",
            meeting_date=date(2026, 6, 7),
        )
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["review-meetings", "run"], input="99\n\n", env={})
    assert result.exit_code == 0
    assert "Invalid choice; event number is out of range." in result.output
    assert len(queue.load()) == 1


def test_review_meetings_handles_unmatched_session_without_candidates(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
title: "zoom"
calendar_event_id: ""
calendar_match_confidence: "none"
calendar_review_queued: true
calendar_candidate_event_ids:
  - ""
calendar_attendees:
  - ""
calendar_candidates:
  - id: ""
---
""",
        encoding="utf-8",
    )
    queue = MeetingReviewQueue(tmp_path / "meeting_review_queue.json")
    monkeypatch.setattr("mt_linux.cli.MeetingReviewQueue", lambda: queue)
    queue.add(
        MeetingReviewEntry(
            session_id="session-2",
            transcript_path=transcript,
            selected_event_id="",
            candidates=[],
            meeting_title="zoom",
            meeting_date=date(2026, 6, 7),
            app="zoom",
            detected_start_time=datetime(2026, 6, 7, 14, 31, tzinfo=UTC),
            recording_duration_minutes=45,
            identified_speakers=["Alice Smith"],
            transcript_preview=["Alice Smith: hello there"],
        )
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["review-meetings", "run"],
        input="n\nWeekly Standup\n",
        env={},
    )
    assert result.exit_code == 0
    assert "No plausible calendar candidates were found." in result.output
    assert "Marked as non-calendar / ad-hoc meeting" in result.output
    assert queue.load() == []


def test_review_meetings_recent_can_clear_pending_job_with_manual_title(tmp_path: Path, monkeypatch):
    store = JobSnapshotStore(tmp_path / "jobs")
    audio_path = write_test_wav(tmp_path / "audio" / "sample.wav", seconds=1)
    job = PipelineJob(
        session_id="session-2",
        app_audio_path=audio_path,
        mic_audio_path=audio_path,
        meeting_info=MeetingInfo(
            app="manual",
            pid=0,
            detection_method="manual",
            start_time=datetime(2026, 6, 9, 13, 50, tzinfo=UTC),
            title="Tymlos Stand Up",
            calendar_event=CalendarEvent(
                event_id="event-1",
                title="Tymlos Stand Up",
                start_time=datetime(2026, 6, 9, 14, 0, tzinfo=UTC),
                end_time=datetime(2026, 6, 9, 14, 30, tzinfo=UTC),
                conferencing_type="teams",
                response_status="accepted",
            ),
            calendar_candidates=[
                CalendarEvent(
                    event_id="event-1",
                    title="Tymlos Stand Up",
                    start_time=datetime(2026, 6, 9, 14, 0, tzinfo=UTC),
                    end_time=datetime(2026, 6, 9, 14, 30, tzinfo=UTC),
                    conferencing_type="teams",
                    response_status="accepted",
                )
            ],
            calendar_match_confidence="matched",
        ),
        status=JobStatus.TRANSCRIBING,
    )
    store.save(job)
    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: AppConfig())
    runner = CliRunner()
    result = runner.invoke(cli, ["review-meetings", "recent"], input="1\nn\nAd Hoc Call\n", env={})
    assert result.exit_code == 0
    assert "Marked as non-calendar / ad-hoc meeting" in result.output
    updated = store.load_one("session-2")
    assert updated is not None
    assert updated.meeting_info.title == "Ad Hoc Call"
    assert updated.meeting_info.calendar_event is None
    assert updated.meeting_info.calendar_match_confidence == "external"


def test_review_meetings_recent_renames_transcript_file_for_manual_title(tmp_path: Path, monkeypatch):
    store = JobSnapshotStore(tmp_path / "jobs")
    transcript = tmp_path / "2026-06-09_13-50_tymlos-stand-up.md"
    transcript.write_text(
        """---
title: "Tymlos Stand Up"
calendar_event_id: "event-1"
calendar_match_confidence: "matched"
calendar_review_queued: false
calendar_candidate_event_ids:
  - "event-1"
calendar_attendees:
  - ""
calendar_candidates:
  - id: "event-1"
    title: "Tymlos Stand Up"
    conferencing: "teams"
    response_status: "accepted"
---
""",
        encoding="utf-8",
    )
    audio_path = write_test_wav(tmp_path / "audio" / "sample.wav", seconds=1)
    job = PipelineJob(
        session_id="session-3",
        app_audio_path=audio_path,
        mic_audio_path=audio_path,
        meeting_info=MeetingInfo(
            app="manual",
            pid=0,
            detection_method="manual",
            start_time=datetime(2026, 6, 9, 13, 50, tzinfo=UTC),
            title="Tymlos Stand Up",
            calendar_event=CalendarEvent(
                event_id="event-1",
                title="Tymlos Stand Up",
                start_time=datetime(2026, 6, 9, 14, 0, tzinfo=UTC),
                end_time=datetime(2026, 6, 9, 14, 30, tzinfo=UTC),
                conferencing_type="teams",
                response_status="accepted",
            ),
            calendar_candidates=[
                CalendarEvent(
                    event_id="event-1",
                    title="Tymlos Stand Up",
                    start_time=datetime(2026, 6, 9, 14, 0, tzinfo=UTC),
                    end_time=datetime(2026, 6, 9, 14, 30, tzinfo=UTC),
                    conferencing_type="teams",
                    response_status="accepted",
                )
            ],
            calendar_match_confidence="matched",
        ),
        status=JobStatus.COMPLETE,
    )
    store.save(job)
    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    cfg = AppConfig()
    cfg.output.folder = str(tmp_path)
    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: cfg)
    runner = CliRunner()
    result = runner.invoke(cli, ["review-meetings", "recent"], input="1\nn\nOps Huddle\n", env={})
    assert result.exit_code == 0
    assert not transcript.exists()
    renamed = tmp_path / "2026-06-09_13-50_ops-huddle.md"
    assert renamed.exists()


def test_review_meetings_recheck_can_auto_match_generic_zoom_note(tmp_path: Path, monkeypatch):
    store = JobSnapshotStore(tmp_path / "jobs")
    transcript = tmp_path / "2026-06-09_17-41_zoom.md"
    transcript.write_text(
        """---
title: "zoom"
calendar_event_id: ""
calendar_match_confidence: "none"
calendar_review_queued: false
calendar_candidate_event_ids:
  - ""
calendar_attendees:
  - ""
calendar_candidates:
  - id: ""
---
""",
        encoding="utf-8",
    )
    audio_path = write_test_wav(tmp_path / "audio" / "sample.wav", seconds=1)
    job = PipelineJob(
        session_id="session-recheck-1",
        app_audio_path=audio_path,
        mic_audio_path=audio_path,
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 9, 17, 41, tzinfo=UTC),
            title="zoom",
            calendar_match_confidence="none",
        ),
        status=JobStatus.COMPLETE,
    )
    store.save(job)
    queue = MeetingReviewQueue(tmp_path / "meeting_review_queue.json")

    class _FakeLookup:
        def enrich(self, meeting_info):
            meeting_info.calendar_event = CalendarEvent(
                event_id="event-1",
                title="Weekly Sync",
                start_time=datetime(2026, 6, 9, 17, 30, tzinfo=UTC),
                end_time=datetime(2026, 6, 9, 18, 0, tzinfo=UTC),
                conferencing_type="zoom",
                response_status="accepted",
            )
            meeting_info.calendar_candidates = [meeting_info.calendar_event]
            meeting_info.calendar_match_confidence = "matched"
            meeting_info.calendar_review_queued = False
            meeting_info.title = "Weekly Sync"
            return meeting_info

    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    monkeypatch.setattr("mt_linux.cli.MeetingReviewQueue", lambda: queue)
    cfg = AppConfig()
    cfg.output.folder = str(tmp_path)
    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: cfg)
    monkeypatch.setattr("mt_linux.cli._calendar_lookup_service", lambda _cfg, _window: _FakeLookup())
    runner = CliRunner()
    result = runner.invoke(cli, ["review-meetings", "recheck", "--session", "session-recheck-1"], env={})
    assert result.exit_code == 0
    assert "session-recheck-1: matched Weekly Sync" in result.output
    updated = store.load_one("session-recheck-1")
    assert updated is not None
    assert updated.meeting_info.title == "Weekly Sync"
    assert updated.meeting_info.calendar_event is not None
    renamed = tmp_path / "2026-06-09_17-41_weekly-sync.md"
    assert renamed.exists()
    assert queue.load() == []


def test_review_meetings_recheck_can_queue_unmatched_generic_zoom_note(tmp_path: Path, monkeypatch):
    store = JobSnapshotStore(tmp_path / "jobs")
    transcript = tmp_path / "2026-06-09_17-41_zoom.md"
    transcript.write_text(
        """---
title: "zoom"
calendar_event_id: ""
calendar_match_confidence: "none"
calendar_review_queued: false
calendar_candidate_event_ids:
  - ""
calendar_attendees:
  - ""
calendar_candidates:
  - id: ""
---
""",
        encoding="utf-8",
    )
    audio_path = write_test_wav(tmp_path / "audio" / "sample.wav", seconds=1)
    job = PipelineJob(
        session_id="session-recheck-2",
        app_audio_path=audio_path,
        mic_audio_path=audio_path,
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 9, 17, 41, tzinfo=UTC),
            title="zoom",
            calendar_match_confidence="none",
        ),
        status=JobStatus.COMPLETE,
    )
    store.save(job)
    queue = MeetingReviewQueue(tmp_path / "meeting_review_queue.json")

    class _FakeLookup:
        def enrich(self, meeting_info):
            meeting_info.calendar_event = None
            meeting_info.calendar_candidates = []
            meeting_info.calendar_match_confidence = "none"
            meeting_info.calendar_review_queued = True
            meeting_info.title = "zoom"
            return meeting_info

    monkeypatch.setattr("mt_linux.cli.JobSnapshotStore", lambda: store)
    monkeypatch.setattr("mt_linux.cli.MeetingReviewQueue", lambda: queue)
    cfg = AppConfig()
    cfg.output.folder = str(tmp_path)
    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: cfg)
    monkeypatch.setattr("mt_linux.cli._calendar_lookup_service", lambda _cfg, _window: _FakeLookup())
    runner = CliRunner()
    result = runner.invoke(cli, ["review-meetings", "recheck", "--session", "session-recheck-2"], env={})
    assert result.exit_code == 0
    assert "session-recheck-2: queued review (0 candidates)" in result.output
    updated = store.load_one("session-recheck-2")
    assert updated is not None
    assert updated.meeting_info.calendar_review_queued is True
    entries = queue.load()
    assert len(entries) == 1
    assert entries[0].session_id == "session-recheck-2"
