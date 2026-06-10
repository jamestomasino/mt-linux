from __future__ import annotations

from datetime import datetime

from mt_linux.config import OpenAIConfig
from mt_linux.detection.calendar_matching import choose_calendar_event
from mt_linux.config import CalendarConfig
from mt_linux.detection.caldav_client import CalDAVCalendarClient
from mt_linux.detection.calendar_client import GoogleCalendarClient
from mt_linux.detection.openai_summary_matcher import OpenAISummaryMatcher
from mt_linux.models import MeetingInfo


class CalendarLookupService:
    def __init__(self, config: CalendarConfig, openai_config: OpenAIConfig | None = None):
        self.config = config
        self._client = None
        self._summary_matcher = OpenAISummaryMatcher(openai_config or OpenAIConfig())

    def enrich(self, meeting_info: MeetingInfo) -> MeetingInfo:
        if not self.config.enabled or self.config.backend == "none":
            return meeting_info
        candidates = self.get_candidate_meetings(meeting_info.start_time)
        if candidates is None:
            return meeting_info
        event, plausible, confidence = choose_calendar_event(meeting_info, candidates)
        meeting_info.calendar_candidates = plausible
        meeting_info.calendar_match_confidence = confidence
        meeting_info.calendar_match_method = "deterministic"
        meeting_info.calendar_match_rationale = ""
        meeting_info.calendar_review_queued = confidence == "ambiguous" or (
            confidence == "none" and _needs_unmatched_review(meeting_info)
        )
        if event is None:
            return meeting_info
        meeting_info.calendar_event = event
        if not meeting_info.title:
            meeting_info.title = event.title
        return meeting_info

    def refine_with_summary(
        self,
        meeting_info: MeetingInfo,
        summary: str,
        *,
        window_minutes: int = 0,
    ) -> MeetingInfo:
        if not self.config.enabled or self.config.backend == "none":
            return meeting_info
        candidates = self.get_candidate_meetings(
            meeting_info.start_time,
            window_minutes=window_minutes or max(self.config.lookup_window_minutes, 45),
        )
        if not candidates:
            return meeting_info
        reviewable = _summary_review_candidates(candidates)
        if not reviewable:
            return meeting_info
        decision = self._summary_matcher.match(summary, meeting_info, reviewable)
        if not decision.event_id:
            if decision.ordered_event_ids:
                meeting_info.calendar_candidates = [
                    candidate for candidate in reviewable if candidate.event_id in decision.ordered_event_ids
                ]
                meeting_info.calendar_review_queued = True
                meeting_info.calendar_match_rationale = decision.rationale
                meeting_info.calendar_match_method = "openai_summary"
            return meeting_info
        selected = next((candidate for candidate in reviewable if candidate.event_id == decision.event_id), None)
        if selected is None:
            return meeting_info
        ordered = [
            candidate
            for event_id in decision.ordered_event_ids
            for candidate in reviewable
            if candidate.event_id == event_id
        ]
        if not ordered:
            ordered = [selected]
        meeting_info.calendar_event = selected
        meeting_info.calendar_candidates = ordered
        meeting_info.calendar_match_method = "openai_summary"
        meeting_info.calendar_match_rationale = decision.rationale
        if decision.confidence == "high":
            meeting_info.calendar_match_confidence = "matched"
            meeting_info.calendar_review_queued = False
            meeting_info.title = selected.title
            return meeting_info
        meeting_info.calendar_match_confidence = "ambiguous"
        meeting_info.calendar_review_queued = True
        return meeting_info

    def get_candidate_meetings(self, when: datetime, *, window_minutes: int = 0):
        client = self._get_client()
        if client is None:
            return None
        try:
            return client.get_candidate_meetings(
                when,
                window_minutes=window_minutes or self.config.lookup_window_minutes,
            )
        except Exception:
            return None

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


def _needs_unmatched_review(meeting_info: MeetingInfo) -> bool:
    title = (meeting_info.title or "").strip().lower()
    app = meeting_info.app.strip().lower()
    return not title or title == app


def _summary_review_candidates(candidates):
    return [
        candidate
        for candidate in candidates
        if candidate.response_status or candidate.attendees or candidate.organizer
    ]
