from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


@dataclass
class Attendee:
    name: str
    email: str = ""

    def display(self) -> str:
        return f"{self.name} <{self.email}>" if self.email else self.name


@dataclass
class CalendarEvent:
    event_id: str
    title: str
    start_time: datetime
    end_time: datetime
    organizer: str = ""
    attendees: list[Attendee] = field(default_factory=list)
    conferencing_url: str = ""
    conferencing_type: str = ""
    response_status: str = ""


@dataclass
class MeetingInfo:
    app: str
    pid: int
    detection_method: str
    start_time: datetime
    stream_id: int | None = None
    bus_name: str | None = None
    title: str | None = None
    calendar_event: CalendarEvent | None = None
    calendar_candidates: list[CalendarEvent] = field(default_factory=list)
    calendar_match_confidence: str = "none"
    calendar_review_queued: bool = False
    calendar_match_method: str = "deterministic"
    calendar_match_rationale: str = ""


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str = "SPEAKER_00"
    confidence: float | None = None
    track: str = "mixed"


@dataclass
class SpeakerIdentity:
    label: str
    name: str
    confidence: str
    similarity: float | None = None
    review_queued: bool = False


@dataclass
class ReviewEntry:
    session_id: str
    speaker_label: str
    sample_path: Path
    calendar_attendees: list[str]
    meeting_title: str | None
    meeting_date: date
    transcript_path: Path

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sample_path"] = str(self.sample_path)
        data["transcript_path"] = str(self.transcript_path)
        data["meeting_date"] = self.meeting_date.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewEntry":
        return cls(
            session_id=data["session_id"],
            speaker_label=data["speaker_label"],
            sample_path=Path(data["sample_path"]),
            calendar_attendees=list(data.get("calendar_attendees", [])),
            meeting_title=data.get("meeting_title"),
            meeting_date=date.fromisoformat(data["meeting_date"]),
            transcript_path=Path(data["transcript_path"]),
        )


@dataclass
class MeetingReviewEntry:
    session_id: str
    transcript_path: Path
    selected_event_id: str
    candidates: list[CalendarEvent]
    meeting_title: str | None
    meeting_date: date
    app: str = ""
    detected_start_time: datetime | None = None
    recording_duration_minutes: int = 0
    identified_speakers: list[str] = field(default_factory=list)
    transcript_preview: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "transcript_path": str(self.transcript_path),
            "selected_event_id": self.selected_event_id,
            "candidates": [_calendar_event_to_dict(item) for item in self.candidates],
            "meeting_title": self.meeting_title,
            "meeting_date": self.meeting_date.isoformat(),
            "app": self.app,
            "detected_start_time": self.detected_start_time.isoformat() if self.detected_start_time else "",
            "recording_duration_minutes": self.recording_duration_minutes,
            "identified_speakers": self.identified_speakers,
            "transcript_preview": self.transcript_preview,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MeetingReviewEntry":
        return cls(
            session_id=data["session_id"],
            transcript_path=Path(data["transcript_path"]),
            selected_event_id=data.get("selected_event_id", ""),
            candidates=[_calendar_event_from_dict(item) for item in data.get("candidates", [])],
            meeting_title=data.get("meeting_title"),
            meeting_date=date.fromisoformat(data["meeting_date"]),
            app=data.get("app", ""),
            detected_start_time=datetime.fromisoformat(data["detected_start_time"])
            if data.get("detected_start_time")
            else None,
            recording_duration_minutes=int(data.get("recording_duration_minutes", 0)),
            identified_speakers=list(data.get("identified_speakers", [])),
            transcript_preview=list(data.get("transcript_preview", [])),
        )


def _calendar_event_to_dict(event: CalendarEvent) -> dict[str, Any]:
    data = asdict(event)
    data["start_time"] = event.start_time.isoformat()
    data["end_time"] = event.end_time.isoformat()
    return data


def _calendar_event_from_dict(data: dict[str, Any]) -> CalendarEvent:
    return CalendarEvent(
        event_id=data["event_id"],
        title=data["title"],
        start_time=datetime.fromisoformat(data["start_time"]),
        end_time=datetime.fromisoformat(data["end_time"]),
        organizer=data.get("organizer", ""),
        attendees=[Attendee(**item) for item in data.get("attendees", [])],
        conferencing_url=data.get("conferencing_url", ""),
        conferencing_type=data.get("conferencing_type", ""),
        response_status=data.get("response_status", ""),
    )
