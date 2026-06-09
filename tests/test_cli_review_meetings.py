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
