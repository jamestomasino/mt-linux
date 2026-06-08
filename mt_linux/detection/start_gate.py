from __future__ import annotations

from datetime import UTC, datetime

from mt_linux.detection.calendar_matching import APP_CONFERENCING_MAP
from mt_linux.detection.calendar_lookup import CalendarLookupService
from mt_linux.models import CalendarEvent, MeetingInfo


class CalendarCoupledStartGate:
    def __init__(
        self,
        calendar_lookup: CalendarLookupService | None,
        gated_apps: set[str] | None = None,
    ) -> None:
        self.calendar_lookup = calendar_lookup
        self.gated_apps = gated_apps or {"teams"}

    def allows(self, app: str, pid: int, stream_id: int) -> bool:
        if app not in self.gated_apps:
            return True
        if self.calendar_lookup is None:
            return False
        meeting_info = MeetingInfo(
            app=app,
            pid=pid,
            detection_method="pipewire",
            start_time=datetime.now(UTC),
            stream_id=stream_id,
        )
        enriched = self.calendar_lookup.enrich(meeting_info)
        return has_accepted_platform_candidate(enriched)


def has_accepted_platform_candidate(meeting_info: MeetingInfo) -> bool:
    conferencing_type = APP_CONFERENCING_MAP.get(meeting_info.app, "")
    if not conferencing_type:
        return False
    return any(
        candidate.conferencing_type == conferencing_type and candidate.response_status == "accepted"
        for candidate in _candidate_events(meeting_info)
    )


def _candidate_events(meeting_info: MeetingInfo) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    if meeting_info.calendar_event is not None:
        events.append(meeting_info.calendar_event)
    seen = {event.event_id for event in events}
    for candidate in meeting_info.calendar_candidates:
        if candidate.event_id in seen:
            continue
        events.append(candidate)
        seen.add(candidate.event_id)
    return events
