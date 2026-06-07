from datetime import UTC, date, datetime
from pathlib import Path

from click.testing import CliRunner

from mt_linux.cli import cli
from mt_linux.models import CalendarEvent, MeetingReviewEntry
from mt_linux.pipeline.meeting_review_queue import MeetingReviewQueue


def test_review_meetings_can_mark_session_as_external(tmp_path: Path, monkeypatch):
    transcript = tmp_path / "meeting.md"
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
        input="n\n",
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
    content = transcript.read_text(encoding="utf-8")
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
