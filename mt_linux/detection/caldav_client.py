from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mt_linux.models import Attendee, CalendarEvent


class CalDAVCalendarClient:
    def __init__(
        self,
        url: str,
        username: str = "",
        password: str = "",
        calendar_name: str = "",
    ):
        self.url = url
        self.username = username
        self.password = password
        self.calendar_name = calendar_name
        self._calendar = None

    def get_current_meeting(
        self,
        now: datetime,
        window_minutes: int = 10,
    ) -> CalendarEvent | None:
        candidates = self.get_candidate_meetings(now, window_minutes=window_minutes)
        if not candidates:
            return None
        now_utc = _ensure_utc(now)
        return min(candidates, key=lambda item: abs((item.start_time - now_utc).total_seconds()))

    def get_candidate_meetings(
        self,
        now: datetime,
        window_minutes: int = 10,
    ) -> list[CalendarEvent]:
        calendar = self._get_calendar()
        now_utc = _ensure_utc(now)
        time_min = now_utc - timedelta(minutes=window_minutes)
        time_max = now_utc + timedelta(minutes=window_minutes)
        events = calendar.search(start=time_min, end=time_max, event=True, expand=True)
        parsed = [_calendar_event_from_caldav(item) for item in events]
        return [item for item in parsed if item is not None]

    def get_attendees(self, event_id: str) -> list[str]:
        calendar = self._get_calendar()
        events = calendar.search(event=True, expand=True)
        for item in events:
            parsed = _calendar_event_from_caldav(item)
            if parsed and parsed.event_id == event_id:
                return [attendee.display() for attendee in parsed.attendees]
        return []

    def _get_calendar(self):
        if self._calendar is None:
            self._calendar = _build_caldav_calendar(
                self.url,
                self.username,
                self.password,
                self.calendar_name,
            )
        return self._calendar


def _build_caldav_calendar(url: str, username: str, password: str, calendar_name: str):
    try:
        import caldav
    except ImportError as exc:
        raise RuntimeError(
            "caldav is not installed. Install the calendar extras to enable CalDAV lookup."
        ) from exc
    client = caldav.DAVClient(url=url, username=username or None, password=password or None)
    principal = client.principal()
    calendars = principal.calendars()
    if not calendars:
        raise RuntimeError("No CalDAV calendars were found.")
    if calendar_name:
        for calendar in calendars:
            if getattr(calendar, "name", None) == calendar_name:
                return calendar
        raise RuntimeError(f"CalDAV calendar '{calendar_name}' was not found.")
    return calendars[0]


def _calendar_event_from_caldav(event) -> CalendarEvent | None:
    icalendar_instance = getattr(event, "icalendar_instance", None)
    if icalendar_instance is None:
        return None
    vevent = getattr(icalendar_instance, "vevent", None)
    if vevent is None:
        return None

    uid = _ical_attr_value(getattr(vevent, "uid", None))
    summary = _ical_attr_value(getattr(vevent, "summary", None)) or "Untitled Meeting"
    dtstart = _ical_datetime_value(getattr(vevent, "dtstart", None))
    dtend = _ical_datetime_value(getattr(vevent, "dtend", None))
    if dtstart is None or dtend is None:
        return None
    organizer = _ical_organizer_name(getattr(vevent, "organizer", None))
    attendees = _ical_attendees(getattr(vevent, "attendee", None))
    conferencing_url = _conference_link_from_text(
        " ".join(
            [
                _ical_attr_value(getattr(vevent, "url", None)),
                _ical_attr_value(getattr(vevent, "location", None)),
                _ical_attr_value(getattr(vevent, "description", None)),
            ]
        )
    )
    return CalendarEvent(
        event_id=uid or summary,
        title=summary,
        start_time=dtstart,
        end_time=dtend,
        organizer=organizer,
        attendees=attendees,
        conferencing_url=conferencing_url,
        conferencing_type=_conferencing_type(conferencing_url),
        response_status=_response_status_from_attendees(getattr(vevent, "attendee", None)),
    )


def _ical_attr_value(value):
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)


def _ical_datetime_value(value) -> datetime | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    if isinstance(raw, datetime):
        return _ensure_utc(raw)
    if hasattr(raw, "year") and hasattr(raw, "month") and hasattr(raw, "day"):
        return datetime(raw.year, raw.month, raw.day, tzinfo=UTC)
    return None


def _ical_organizer_name(value) -> str:
    if value is None:
        return ""
    params = getattr(value, "params", {}) or {}
    common_name = params.get("CN") or params.get("cn")
    if common_name:
        return str(common_name)
    raw = _ical_attr_value(value)
    return raw.removeprefix("mailto:")


def _ical_attendees(value) -> list[Attendee]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    attendees: list[Attendee] = []
    for item in values:
        params = getattr(item, "params", {}) or {}
        common_name = str(params.get("CN") or params.get("cn") or "").strip()
        email = _ical_attr_value(item).removeprefix("mailto:")
        attendees.append(Attendee(name=common_name or email, email=email))
    return attendees


def _conference_link_from_text(value: str) -> str:
    for token in value.split():
        lower = token.lower()
        if "zoom.us/" in lower or "teams.microsoft.com/" in lower or "meet.google.com/" in lower:
            return token.strip("()[]<>,")
    return ""


def _conferencing_type(value: str) -> str:
    value_lower = value.lower()
    if "zoom" in value_lower:
        return "zoom"
    if "teams" in value_lower:
        return "teams"
    if "meet.google.com" in value_lower or "google meet" in value_lower:
        return "meet"
    return ""


def _response_status_from_attendees(value) -> str:
    if value is None:
        return ""
    values = value if isinstance(value, list) else [value]
    for item in values:
        params = getattr(item, "params", {}) or {}
        partstat = params.get("PARTSTAT") or params.get("partstat")
        if partstat:
            return str(partstat).lower()
    return ""


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
