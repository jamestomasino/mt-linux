from datetime import UTC, date, datetime
from pathlib import Path

from mt_linux.models import CalendarEvent, MeetingReviewEntry
from mt_linux.pipeline.meeting_review_queue import MeetingReviewQueue


def test_meeting_review_queue_round_trips_entries(tmp_path: Path):
    queue = MeetingReviewQueue(tmp_path / "meeting_review.json")
    entry = MeetingReviewEntry(
        session_id="session-1",
        transcript_path=tmp_path / "meeting.md",
        selected_event_id="event-1",
        candidates=[
            CalendarEvent(
                event_id="event-1",
                title="Weekly Standup",
                start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
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
        identified_speakers=["Alice Smith", "Bob Jones"],
        transcript_preview=["SPEAKER_00: Hello", "SPEAKER_01: Hi"],
    )
    queue.add(entry)
    loaded = queue.load()
    assert len(loaded) == 1
    assert loaded[0].selected_event_id == "event-1"
    assert loaded[0].candidates[0].conferencing_type == "zoom"
    assert loaded[0].app == "zoom"
    assert loaded[0].recording_duration_minutes == 45
    assert loaded[0].transcript_preview == ["SPEAKER_00: Hello", "SPEAKER_01: Hi"]
