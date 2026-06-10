from datetime import UTC, datetime

from mt_linux.detection.calendar_matching import choose_calendar_event
from mt_linux.models import CalendarEvent, MeetingInfo


def test_choose_calendar_event_ignores_non_conferencing_events():
    meeting = MeetingInfo(app="zoom", pid=1, detection_method="pipewire", start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC))
    chosen, candidates, confidence = choose_calendar_event(
        meeting,
        [
            CalendarEvent(
                event_id="event-1",
                title="No Link",
                start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
            )
        ],
    )
    assert chosen is None
    assert candidates == []
    assert confidence == "none"


def test_choose_calendar_event_surfaces_nonconference_candidates_for_review():
    meeting = MeetingInfo(app="zoom", pid=1, detection_method="pipewire", start_time=datetime(2026, 6, 7, 14, 31, tzinfo=UTC))
    chosen, candidates, confidence = choose_calendar_event(
        meeting,
        [
            CalendarEvent(
                event_id="home",
                title="Home",
                start_time=datetime(2026, 6, 7, 0, 0, tzinfo=UTC),
                end_time=datetime(2026, 6, 8, 0, 0, tzinfo=UTC),
            ),
            CalendarEvent(
                event_id="a",
                title="James/Brandon-Weekly 1:1",
                start_time=datetime(2026, 6, 7, 17, 0, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 17, 30, tzinfo=UTC),
                response_status="accepted",
            ),
        ],
    )
    assert chosen is None
    assert confidence == "none"
    assert [item.title for item in candidates] == ["James/Brandon-Weekly 1:1"]


def test_choose_calendar_event_prefers_accepted_zoom_and_marks_ties_ambiguous():
    meeting = MeetingInfo(app="zoom", pid=1, detection_method="pipewire", start_time=datetime(2026, 6, 7, 14, 31, tzinfo=UTC))
    chosen, candidates, confidence = choose_calendar_event(
        meeting,
        [
            CalendarEvent(
                event_id="a",
                title="A",
                start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                conferencing_url="https://princeton.zoom.us/j/1",
                conferencing_type="zoom",
                response_status="accepted",
            ),
            CalendarEvent(
                event_id="b",
                title="B",
                start_time=datetime(2026, 6, 7, 14, 32, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                conferencing_url="https://princeton.zoom.us/j/2",
                conferencing_type="zoom",
                response_status="accepted",
            ),
        ],
    )
    assert chosen is not None
    assert confidence == "ambiguous"
    assert len(candidates) == 2
