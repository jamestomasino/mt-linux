from datetime import UTC, datetime

from mt_linux.config import CalendarConfig, OpenAIConfig
from mt_linux.detection.calendar_lookup import CalendarLookupService
from mt_linux.models import Attendee, CalendarEvent, MeetingInfo


class _FakeClient:
    def __init__(self, events):
        self.events = events

    def get_candidate_meetings(self, now, window_minutes=10):
        return self.events


def test_calendar_lookup_service_enriches_meeting_info():
    service = CalendarLookupService(CalendarConfig())
    service._client = _FakeClient(
        [
            CalendarEvent(
                event_id="event-1",
                title="Weekly Standup",
                start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                organizer="Alice Smith",
                attendees=[Attendee(name="Bob", email="bob@example.com")],
                conferencing_url="https://princeton.zoom.us/j/123",
                conferencing_type="zoom",
                response_status="accepted",
            )
        ]
    )
    meeting = MeetingInfo(
        app="zoom",
        pid=100,
        detection_method="pipewire",
        start_time=datetime(2026, 6, 7, 14, 31, tzinfo=UTC),
    )
    enriched = service.enrich(meeting)
    assert enriched.title == "Weekly Standup"
    assert enriched.calendar_event is not None
    assert enriched.calendar_event.organizer == "Alice Smith"
    assert enriched.calendar_match_confidence == "matched"


def test_calendar_lookup_service_uses_caldav_backend():
    config = CalendarConfig(backend="caldav", caldav_url="https://calendar.example.com")
    service = CalendarLookupService(config)
    service._client = _FakeClient(
        [
            CalendarEvent(
                event_id="event-2",
                title="CalDAV Standup",
                start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                organizer="Bob Jones",
                attendees=[Attendee(name="Alice", email="alice@example.com")],
                conferencing_url="https://princeton.zoom.us/j/999",
                conferencing_type="zoom",
                response_status="accepted",
            )
        ]
    )
    meeting = MeetingInfo(
        app="teams",
        pid=200,
        detection_method="pipewire",
        start_time=datetime(2026, 6, 7, 14, 31, tzinfo=UTC),
    )
    enriched = service.enrich(meeting)
    assert enriched.title == "CalDAV Standup"
    assert enriched.calendar_event is not None
    assert enriched.calendar_event.organizer == "Bob Jones"


def test_calendar_lookup_service_marks_ambiguous_candidates():
    service = CalendarLookupService(CalendarConfig())
    service._client = _FakeClient(
        [
            CalendarEvent(
                event_id="event-1",
                title="Weekly Standup",
                start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                conferencing_url="https://princeton.zoom.us/j/123",
                conferencing_type="zoom",
                response_status="accepted",
            ),
            CalendarEvent(
                event_id="event-2",
                title="Customer Call",
                start_time=datetime(2026, 6, 7, 14, 31, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
                conferencing_url="https://princeton.zoom.us/j/456",
                conferencing_type="zoom",
                response_status="accepted",
            ),
        ]
    )
    meeting = MeetingInfo(
        app="zoom",
        pid=100,
        detection_method="pipewire",
        start_time=datetime(2026, 6, 7, 14, 31, tzinfo=UTC),
    )
    enriched = service.enrich(meeting)
    assert enriched.calendar_event is not None
    assert enriched.calendar_match_confidence == "ambiguous"
    assert enriched.calendar_review_queued is True
    assert len(enriched.calendar_candidates) == 2


def test_calendar_lookup_service_queues_unmatched_generic_app_titles_for_review():
    service = CalendarLookupService(CalendarConfig())
    service._client = _FakeClient([])
    meeting = MeetingInfo(
        app="zoom",
        pid=100,
        detection_method="pipewire",
        start_time=datetime(2026, 6, 7, 14, 31, tzinfo=UTC),
    )
    enriched = service.enrich(meeting)
    assert enriched.calendar_match_confidence == "none"
    assert enriched.calendar_review_queued is True
    assert enriched.calendar_candidates == []


def test_calendar_lookup_service_refines_with_openai_summary(monkeypatch):
    service = CalendarLookupService(
        CalendarConfig(),
        OpenAIConfig(enabled=True, api_key="test-key", model="gpt-test"),
    )
    service._client = _FakeClient(
        [
            CalendarEvent(
                event_id="event-1",
                title="James/Brandon-Weekly 1:1",
                start_time=datetime(2026, 6, 7, 17, 0, tzinfo=UTC),
                end_time=datetime(2026, 6, 7, 17, 30, tzinfo=UTC),
                organizer="james@example.com",
                attendees=[Attendee(name="Brandon", email="brandon@example.com")],
                response_status="accepted",
            )
        ]
    )
    monkeypatch.setattr(
        service._summary_matcher,
        "match",
        lambda summary, meeting_info, candidates: type(
            "Decision",
            (),
            {
                "event_id": "event-1",
                "confidence": "high",
                "rationale": "James and Brandon appear in the summary.",
                "ordered_event_ids": ["event-1"],
            },
        )(),
    )
    meeting = MeetingInfo(
        app="zoom",
        pid=100,
        detection_method="pipewire",
        start_time=datetime(2026, 6, 7, 17, 41, tzinfo=UTC),
        title="zoom",
        calendar_match_confidence="none",
    )
    enriched = service.refine_with_summary(meeting, "James and Brandon discussed weekly priorities.")
    assert enriched.calendar_event is not None
    assert enriched.calendar_event.title == "James/Brandon-Weekly 1:1"
    assert enriched.calendar_match_confidence == "matched"
    assert enriched.calendar_match_method == "openai_summary"
