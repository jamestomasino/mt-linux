from __future__ import annotations

from datetime import datetime

from mt_linux.detection.calendar_matching import choose_calendar_event
from mt_linux.config import CalendarConfig
from mt_linux.detection.caldav_client import CalDAVCalendarClient
from mt_linux.detection.calendar_client import GoogleCalendarClient
from mt_linux.models import MeetingInfo


class CalendarLookupService:
    def __init__(self, config: CalendarConfig):
        self.config = config
        self._client = None

    def enrich(self, meeting_info: MeetingInfo) -> MeetingInfo:
        if not self.config.enabled or self.config.backend == "none":
            return meeting_info
        client = self._get_client()
        if client is None:
            return meeting_info
        try:
            candidates = client.get_candidate_meetings(
                meeting_info.start_time,
                window_minutes=self.config.lookup_window_minutes,
            )
        except Exception:
            return meeting_info
        event, plausible, confidence = choose_calendar_event(meeting_info, candidates)
        meeting_info.calendar_candidates = plausible
        meeting_info.calendar_match_confidence = confidence
        meeting_info.calendar_review_queued = confidence == "ambiguous"
        if event is None:
            return meeting_info
        meeting_info.calendar_event = event
        if not meeting_info.title:
            meeting_info.title = event.title
        return meeting_info

    def _get_client(self) -> GoogleCalendarClient | None:
        if self._client is not None:
            return self._client
        if self.config.backend == "google":
            token_path = self.config.token_path
            if not token_path:
                return None
            self._client = GoogleCalendarClient(
                self.config.credentials_path,
                self.config.token_path,
            )
        elif self.config.backend == "caldav":
            if not self.config.caldav_url:
                return None
            self._client = CalDAVCalendarClient(
                self.config.caldav_url,
                username=self.config.caldav_username,
                password=self.config.caldav_password,
                calendar_name=self.config.caldav_calendar_name,
            )
        else:
            return None
        return self._client
