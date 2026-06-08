from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from mt_linux.models import Attendee, CalendarEvent, MeetingInfo
from mt_linux.diarization.diarizer import DiarizationSegment
from mt_linux.models import TranscriptSegment


class JobStatus(str, Enum):
    PENDING = "pending"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    DIARIZING = "diarizing"
    DIARIZED = "diarized"
    GENERATING_PROTOCOL = "generating_protocol"
    WRITING_OUTPUT = "writing_output"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class PipelineJob:
    session_id: str
    app_audio_path: Path
    mic_audio_path: Path
    meeting_info: MeetingInfo
    imported_audio_path: Path | None = None
    status: JobStatus = JobStatus.PENDING
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    transcript_segments: list[TranscriptSegment] | None = None
    diarization_segments: list[DiarizationSegment] | None = None
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        meeting = asdict(self.meeting_info)
        if self.meeting_info.calendar_event:
            meeting["calendar_event"]["start_time"] = self.meeting_info.calendar_event.start_time.isoformat()
            meeting["calendar_event"]["end_time"] = self.meeting_info.calendar_event.end_time.isoformat()
        for candidate in meeting.get("calendar_candidates", []):
            candidate["start_time"] = datetime.fromisoformat(candidate["start_time"]).isoformat() if isinstance(candidate["start_time"], str) else candidate["start_time"].isoformat()
            candidate["end_time"] = datetime.fromisoformat(candidate["end_time"]).isoformat() if isinstance(candidate["end_time"], str) else candidate["end_time"].isoformat()
        meeting["start_time"] = self.meeting_info.start_time.isoformat()
        return {
            "session_id": self.session_id,
            "app_audio_path": str(self.app_audio_path),
            "mic_audio_path": str(self.mic_audio_path),
            "imported_audio_path": str(self.imported_audio_path) if self.imported_audio_path else None,
            "meeting_info": meeting,
            "status": self.status.value,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "transcript_segments": [asdict(segment) for segment in self.transcript_segments]
            if self.transcript_segments is not None
            else None,
            "diarization_segments": [asdict(segment) for segment in self.diarization_segments]
            if self.diarization_segments is not None
            else None,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineJob":
        event_data = data["meeting_info"].get("calendar_event")
        calendar_event = None
        if event_data:
            calendar_event = CalendarEvent(
                event_id=event_data["event_id"],
                title=event_data["title"],
                start_time=datetime.fromisoformat(event_data["start_time"]),
                end_time=datetime.fromisoformat(event_data["end_time"]),
                organizer=event_data.get("organizer", ""),
                attendees=[
                    Attendee(name=item.get("name", ""), email=item.get("email", ""))
                    for item in event_data.get("attendees", [])
                ],
            )
        meeting_info = MeetingInfo(
            app=data["meeting_info"]["app"],
            pid=int(data["meeting_info"]["pid"]),
            detection_method=data["meeting_info"]["detection_method"],
            start_time=datetime.fromisoformat(data["meeting_info"]["start_time"]),
            stream_id=data["meeting_info"].get("stream_id"),
            bus_name=data["meeting_info"].get("bus_name"),
            title=data["meeting_info"].get("title"),
            calendar_event=calendar_event,
            calendar_candidates=[
                CalendarEvent(
                    event_id=item["event_id"],
                    title=item["title"],
                    start_time=datetime.fromisoformat(item["start_time"]),
                    end_time=datetime.fromisoformat(item["end_time"]),
                    organizer=item.get("organizer", ""),
                    attendees=[
                        Attendee(name=attendee.get("name", ""), email=attendee.get("email", ""))
                        for attendee in item.get("attendees", [])
                    ],
                    conferencing_url=item.get("conferencing_url", ""),
                    conferencing_type=item.get("conferencing_type", ""),
                    response_status=item.get("response_status", ""),
                )
                for item in data["meeting_info"].get("calendar_candidates", [])
            ],
            calendar_match_confidence=data["meeting_info"].get("calendar_match_confidence", "none"),
            calendar_review_queued=bool(data["meeting_info"].get("calendar_review_queued", False)),
        )
        return cls(
            session_id=data["session_id"],
            app_audio_path=Path(data["app_audio_path"]),
            mic_audio_path=Path(data["mic_audio_path"]),
            meeting_info=meeting_info,
            imported_audio_path=Path(data["imported_audio_path"]) if data.get("imported_audio_path") else None,
            status=JobStatus(data.get("status", JobStatus.PENDING.value)),
            error=data.get("error"),
            created_at=datetime.fromisoformat(data["created_at"]),
            transcript_segments=[
                TranscriptSegment(**item) for item in data["transcript_segments"]
            ]
            if data.get("transcript_segments") is not None
            else None,
            diarization_segments=[
                DiarizationSegment(**item) for item in data["diarization_segments"]
            ]
            if data.get("diarization_segments") is not None
            else None,
            summary=data.get("summary"),
        )
