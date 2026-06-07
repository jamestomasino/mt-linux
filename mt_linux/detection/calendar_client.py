from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from mt_linux.config import expand_path
from mt_linux.models import Attendee, CalendarEvent


class GoogleCalendarClient:
    def __init__(self, credentials_path: str, token_path: str):
        self.credentials_path = expand_path(credentials_path)
        self.token_path = expand_path(token_path)
        self._service = None

    def get_current_meeting(
        self, now: datetime, window_minutes: int = 10
    ) -> CalendarEvent | None:
        candidates = self.get_candidate_meetings(now, window_minutes=window_minutes)
        if not candidates:
            return None
        return min(candidates, key=lambda item: abs((item.start_time - _ensure_utc(now)).total_seconds()))

    def get_candidate_meetings(
        self, now: datetime, window_minutes: int = 10
    ) -> list[CalendarEvent]:
        service = self._get_service()
        now_utc = _ensure_utc(now)
        time_min = (now_utc - timedelta(minutes=window_minutes)).isoformat()
        time_max = (now_utc + timedelta(minutes=window_minutes)).isoformat()
        response = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        items = response.get("items", [])
        return [_calendar_event_from_google_item(item) for item in items]

    def get_attendees(self, event_id: str) -> list[str]:
        service = self._get_service()
        item = service.events().get(calendarId="primary", eventId=event_id).execute()
        return [attendee.display() for attendee in _attendees_from_google_item(item)]

    def _get_service(self):
        if self._service is None:
            self._service = _build_google_calendar_service(self.token_path)
        return self._service


def _build_google_calendar_service(token_path: Path):
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google Calendar dependencies are not installed. Install the calendar extras to enable calendar lookup."
        ) from exc
    credentials = Credentials.from_authorized_user_file(
        str(token_path),
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    return build("calendar", "v3", credentials=credentials)


def _calendar_event_from_google_item(item: dict) -> CalendarEvent:
    return CalendarEvent(
        event_id=item.get("id", ""),
        title=item.get("summary", "Untitled Meeting"),
        start_time=_parse_google_datetime(item["start"]),
        end_time=_parse_google_datetime(item["end"]),
        organizer=item.get("organizer", {}).get("displayName", item.get("organizer", {}).get("email", "")),
        attendees=_attendees_from_google_item(item),
        conferencing_url=_google_conferencing_url(item),
        conferencing_type=_conferencing_type(_google_conferencing_url(item)),
        response_status=_google_response_status(item),
    )


def _attendees_from_google_item(item: dict) -> list[Attendee]:
    attendees = []
    for attendee in item.get("attendees", []):
        attendees.append(
            Attendee(
                name=attendee.get("displayName", attendee.get("email", "")),
                email=attendee.get("email", ""),
            )
        )
    return attendees


def _parse_google_datetime(value: dict) -> datetime:
    raw = value.get("dateTime")
    if raw:
        return _ensure_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    day = datetime.fromisoformat(value["date"])
    return day.replace(tzinfo=UTC)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _google_conferencing_url(item: dict) -> str:
    candidates = [
        item.get("hangoutLink", ""),
        item.get("location", ""),
        item.get("description", ""),
    ]
    for candidate in candidates:
        url = _extract_known_conference_link(candidate)
        if url:
            return url
    return ""


def _google_response_status(item: dict) -> str:
    for attendee in item.get("attendees", []):
        if attendee.get("self"):
            return attendee.get("responseStatus", "")
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


def _extract_known_conference_link(value: str) -> str:
    for token in value.split():
        lower = token.lower()
        if "zoom.us/" in lower or "teams.microsoft.com/" in lower or "meet.google.com/" in lower:
            return token.strip("()[]<>,")
    return ""
