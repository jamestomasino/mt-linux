from __future__ import annotations

from datetime import datetime

from mt_linux.models import CalendarEvent, MeetingInfo


APP_CONFERENCING_MAP = {
    "zoom": "zoom",
    "teams": "teams",
    "meet": "meet",
}


def choose_calendar_event(
    meeting_info: MeetingInfo,
    candidates: list[CalendarEvent],
) -> tuple[CalendarEvent | None, list[CalendarEvent], str]:
    filtered = [item for item in candidates if item.conferencing_type or item.conferencing_url]
    if not filtered:
        plausible = [item for item in candidates if _reviewable_without_conferencing(item)]
        plausible = sorted(
            plausible,
            key=lambda item: _score_nonconference_candidate(meeting_info, item),
            reverse=True,
        )
        return None, plausible, "none"

    scored = sorted(
        filtered,
        key=lambda item: _score_candidate(meeting_info, item),
        reverse=True,
    )
    top = scored[0]
    top_score = _score_candidate(meeting_info, top)
    plausible = [
        item
        for item in scored
        if _same_strength(meeting_info, top, item)
    ]
    if len(plausible) > 1:
        plausible = sorted(plausible, key=lambda item: abs((item.start_time - meeting_info.start_time).total_seconds()))
        return plausible[0], plausible, "ambiguous"
    return top, [top], "matched"


def _score_candidate(meeting_info: MeetingInfo, candidate: CalendarEvent) -> tuple[int, int, int]:
    platform_match = int(candidate.conferencing_type == APP_CONFERENCING_MAP.get(meeting_info.app, ""))
    accepted = int(candidate.response_status == "accepted")
    proximity = -int(abs((candidate.start_time - meeting_info.start_time).total_seconds()))
    return platform_match, accepted, proximity


def _same_strength(meeting_info: MeetingInfo, top: CalendarEvent, other: CalendarEvent) -> bool:
    top_base = _score_candidate(meeting_info, top)[:2]
    other_base = _score_candidate(meeting_info, other)[:2]
    if top_base != other_base:
        return False
    if top_base == (0, 0):
        return top.event_id == other.event_id
    top_delta = abs((top.start_time - meeting_info.start_time).total_seconds())
    other_delta = abs((other.start_time - meeting_info.start_time).total_seconds())
    return abs(top_delta - other_delta) <= 300


def _reviewable_without_conferencing(candidate: CalendarEvent) -> bool:
    return bool(candidate.response_status)


def _score_nonconference_candidate(meeting_info: MeetingInfo, candidate: CalendarEvent) -> tuple[int, int]:
    accepted = int(candidate.response_status == "accepted")
    proximity = -int(abs((candidate.start_time - meeting_info.start_time).total_seconds()))
    return accepted, proximity
