from __future__ import annotations

from dataclasses import dataclass, field
import json
import re

from mt_linux.config import OpenAIConfig
from mt_linux.models import CalendarEvent, MeetingInfo


@dataclass
class SummaryMatchDecision:
    event_id: str = ""
    confidence: str = "none"
    rationale: str = ""
    ordered_event_ids: list[str] = field(default_factory=list)


class OpenAISummaryMatcher:
    def __init__(self, config: OpenAIConfig):
        self.config = config

    def enabled(self) -> bool:
        return bool(
            self.config.enabled
            and self.config.api_key.strip()
            and self.config.model.strip()
        )

    def match(
        self,
        summary: str,
        meeting_info: MeetingInfo,
        candidates: list[CalendarEvent],
    ) -> SummaryMatchDecision:
        if not self.enabled() or not summary.strip() or not candidates:
            return SummaryMatchDecision()
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required for OpenAI meeting matching.") from exc
        payload = {
            "model": self.config.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {
                    "role": "user",
                    "content": _user_prompt(summary, meeting_info, candidates),
                },
            ],
        }
        response = httpx.post(
            self.config.endpoint,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return _parse_decision(content, candidates)


def _system_prompt() -> str:
    return (
        "You are ranking nearby calendar events for a recorded meeting. "
        "Use the meeting summary, detected app, start time, speaker names, and attendee/title clues. "
        "Prefer semantic fit over conferencing-link presence. "
        "Return JSON only with keys: event_id, confidence, rationale, ordered_event_ids. "
        "confidence must be one of: high, medium, low, none. "
        "If no candidate matches, use an empty event_id and confidence none."
    )


def _user_prompt(summary: str, meeting_info: MeetingInfo, candidates: list[CalendarEvent]) -> str:
    speaker_names = sorted(
        {
            name
            for name in re.findall(r"\[\[([^\]]+)\]\]", summary)
            if name and "speaker_" not in name.lower()
        }
    )
    candidate_lines = []
    for candidate in candidates:
        candidate_lines.append(
            json.dumps(
                {
                    "event_id": candidate.event_id,
                    "title": candidate.title,
                    "start_time": candidate.start_time.isoformat(),
                    "end_time": candidate.end_time.isoformat(),
                    "organizer": candidate.organizer,
                    "attendees": [attendee.display() for attendee in candidate.attendees],
                    "conferencing_type": candidate.conferencing_type,
                    "response_status": candidate.response_status,
                },
                ensure_ascii=True,
            )
        )
    return "\n".join(
        [
            f"Detected app: {meeting_info.app}",
            f"Detected start time: {meeting_info.start_time.isoformat()}",
            f"Current title: {meeting_info.title or ''}",
            f"Speaker names seen in summary: {', '.join(speaker_names)}",
            "Meeting summary:",
            summary.strip(),
            "",
            "Calendar candidates:",
            *candidate_lines,
        ]
    )


def _parse_decision(content: str, candidates: list[CalendarEvent]) -> SummaryMatchDecision:
    candidate_ids = {candidate.event_id for candidate in candidates}
    data = json.loads(content)
    event_id = data.get("event_id", "")
    if event_id not in candidate_ids:
        event_id = ""
    confidence = str(data.get("confidence", "none")).lower()
    if confidence not in {"high", "medium", "low", "none"}:
        confidence = "none"
    ordered_event_ids = [
        item for item in data.get("ordered_event_ids", []) if item in candidate_ids
    ]
    if not ordered_event_ids and event_id:
        ordered_event_ids = [event_id]
    return SummaryMatchDecision(
        event_id=event_id,
        confidence=confidence,
        rationale=str(data.get("rationale", "")).strip(),
        ordered_event_ids=ordered_event_ids,
    )
