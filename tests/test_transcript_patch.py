from pathlib import Path

from mt_linux.models import CalendarEvent
from datetime import UTC, datetime

from mt_linux.output.transcript_patch import (
    apply_meeting_assignment,
    clear_meeting_assignment,
    replace_speaker_label,
)


def test_replace_speaker_label_updates_transcript_and_frontmatter(tmp_path: Path):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
participants_identified:
  - name: "SPEAKER_01"
    confidence: "unidentified"
    review_queued: true
---

**14:30:00** SPEAKER_01: Hello
""",
        encoding="utf-8",
    )
    replace_speaker_label(transcript, "SPEAKER_01", "Alice Smith")
    content = transcript.read_text(encoding="utf-8")
    assert "[[Alice Smith]]: Hello" in content
    assert 'name: "[[Alice Smith]]"' in content
    assert 'confidence: "voice_profile"' in content


def test_apply_meeting_assignment_updates_calendar_frontmatter(tmp_path: Path):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
title: "Old Title"
duration_minutes: 10
organizer: ""
calendar_event_id: ""
calendar_match_confidence: "ambiguous"
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
    apply_meeting_assignment(
        transcript,
        selected_event=CalendarEvent(
            event_id="event-1",
            title="Weekly Standup",
            start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
            end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
            organizer="Alice Smith",
            attendees=[],
            conferencing_type="zoom",
            response_status="accepted",
        ),
        candidates=[
            CalendarEvent(
                event_id="event-1",
                title="Weekly Standup",
                start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                organizer="Alice Smith",
                attendees=[],
                conferencing_type="zoom",
                response_status="accepted",
            )
        ],
        ambiguous=False,
    )
    content = transcript.read_text(encoding="utf-8")
    assert 'calendar_event_id: "event-1"' in content
    assert 'calendar_review_queued: false' in content
    assert 'title: "Weekly Standup"' in content
    assert "duration_minutes: 30" in content


def test_clear_meeting_assignment_marks_transcript_external(tmp_path: Path):
    transcript = tmp_path / "meeting.md"
    transcript.write_text(
        """---
title: "Wrong Calendar Meeting"
duration_minutes: 45
organizer: "[[Alice Smith]]"
calendar_event_id: "event-1"
calendar_match_confidence: "ambiguous"
calendar_review_queued: true
calendar_candidate_event_ids:
  - "event-1"
calendar_attendees:
  - "Alice Smith <alice@example.com>"
calendar_candidates:
  - id: "event-1"
    title: "Weekly Standup"
    conferencing: "zoom"
    response_status: "accepted"
---
""",
        encoding="utf-8",
    )
    clear_meeting_assignment(
        transcript,
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
    )
    content = transcript.read_text(encoding="utf-8")
    assert 'calendar_event_id: ""' in content
    assert 'calendar_match_confidence: "external"' in content
    assert 'calendar_review_queued: false' in content
    assert 'organizer: ""' in content
    assert 'title: "Ad Hoc Meeting"' in content
    assert "duration_minutes: 0" in content
