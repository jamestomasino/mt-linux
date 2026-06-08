from datetime import UTC, datetime

from mt_linux.config import CalendarConfig
from mt_linux.detection.calendar_lookup import CalendarLookupService
from mt_linux.detection.start_gate import CalendarCoupledStartGate, has_accepted_platform_candidate
from mt_linux.models import CalendarEvent, MeetingInfo


class _FakeCalendarLookup(CalendarLookupService):
    def __init__(self, enriched: MeetingInfo):
        super().__init__(CalendarConfig())
        self.enriched = enriched

    def enrich(self, meeting_info: MeetingInfo) -> MeetingInfo:
        return self.enriched


def test_start_gate_allows_zoom_without_calendar_check():
    gate = CalendarCoupledStartGate(calendar_lookup=None)
    assert gate.allows("zoom", 100, 1) is True


def test_start_gate_denies_teams_without_calendar_lookup():
    gate = CalendarCoupledStartGate(calendar_lookup=None)
    assert gate.allows("teams", 100, 1) is False


def test_start_gate_allows_teams_with_accepted_teams_event():
    event = CalendarEvent(
        event_id="event-1",
        title="Teams Standup",
        start_time=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, 8, 12, 30, tzinfo=UTC),
        conferencing_url="https://teams.microsoft.com/l/meetup-join/123",
        conferencing_type="teams",
        response_status="accepted",
    )
    enriched = MeetingInfo(
        app="teams",
        pid=100,
        detection_method="pipewire",
        start_time=datetime(2026, 6, 8, 12, 1, tzinfo=UTC),
        calendar_event=event,
        calendar_candidates=[event],
    )
    gate = CalendarCoupledStartGate(_FakeCalendarLookup(enriched))
    assert gate.allows("teams", 100, 1) is True


def test_start_gate_denies_teams_without_accepted_teams_event():
    event = CalendarEvent(
        event_id="event-1",
        title="Tentative Teams Sync",
        start_time=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, 8, 12, 30, tzinfo=UTC),
        conferencing_url="https://teams.microsoft.com/l/meetup-join/123",
        conferencing_type="teams",
        response_status="tentative",
    )
    enriched = MeetingInfo(
        app="teams",
        pid=100,
        detection_method="pipewire",
        start_time=datetime(2026, 6, 8, 12, 1, tzinfo=UTC),
        calendar_event=event,
        calendar_candidates=[event],
    )
    gate = CalendarCoupledStartGate(_FakeCalendarLookup(enriched))
    assert gate.allows("teams", 100, 1) is False


def test_has_accepted_platform_candidate_uses_ambiguous_candidates():
    accepted = CalendarEvent(
        event_id="event-1",
        title="Teams Standup",
        start_time=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, 8, 12, 30, tzinfo=UTC),
        conferencing_url="https://teams.microsoft.com/l/meetup-join/123",
        conferencing_type="teams",
        response_status="accepted",
    )
    other = CalendarEvent(
        event_id="event-2",
        title="Other Call",
        start_time=datetime(2026, 6, 8, 12, 2, tzinfo=UTC),
        end_time=datetime(2026, 6, 8, 12, 30, tzinfo=UTC),
        conferencing_url="https://teams.microsoft.com/l/meetup-join/456",
        conferencing_type="teams",
        response_status="accepted",
    )
    info = MeetingInfo(
        app="teams",
        pid=100,
        detection_method="pipewire",
        start_time=datetime(2026, 6, 8, 12, 1, tzinfo=UTC),
        calendar_candidates=[accepted, other],
        calendar_match_confidence="ambiguous",
        calendar_review_queued=True,
    )
    assert has_accepted_platform_candidate(info) is True
