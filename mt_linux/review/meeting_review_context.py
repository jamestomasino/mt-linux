from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from mt_linux.models import CalendarEvent, MeetingReviewEntry


def format_candidate_summary(candidate: CalendarEvent, detected_start_time: datetime) -> str:
    delta_minutes = int((candidate.start_time - detected_start_time).total_seconds() // 60)
    sign = "+" if delta_minutes >= 0 else "-"
    domain = urlparse(candidate.conferencing_url).netloc or candidate.conferencing_type or "unknown"
    return (
        f"[{candidate.conferencing_type or 'unknown'}] "
        f"{candidate.response_status or 'no-response'} "
        f"{candidate.start_time.isoformat()} "
        f"({sign}{abs(delta_minutes)}m) "
        f"organizer={candidate.organizer or 'unknown'} "
        f"attendees={len(candidate.attendees)} "
        f"link={domain}"
    )


def format_transcript_preview(entry: MeetingReviewEntry) -> list[str]:
    return entry.transcript_preview[:5]
