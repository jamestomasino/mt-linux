from __future__ import annotations

import asyncio
from dataclasses import dataclass

from mt_linux.audio.capture import CaptureSession, create_session_paths
from mt_linux.audio.session_recorder import PlaceholderRecorder, RecordingHandle, SessionRecorder
from mt_linux.detection.calendar_lookup import CalendarLookupService
from mt_linux.models import MeetingInfo
from mt_linux.pipeline.job import PipelineJob
from mt_linux.pipeline.queue import PipelineQueue


@dataclass
class ActiveMeeting:
    meeting_info: MeetingInfo
    capture_session: CaptureSession
    recording_handle: RecordingHandle


class MeetingSessionManager:
    def __init__(
        self,
        queue: PipelineQueue,
        calendar_lookup: CalendarLookupService,
        recorder: SessionRecorder | None = None,
    ):
        self.queue = queue
        self.calendar_lookup = calendar_lookup
        self.recorder = recorder or PlaceholderRecorder()
        self._active: ActiveMeeting | None = None

    @property
    def active(self) -> ActiveMeeting | None:
        return self._active

    async def handle_meeting_start(self, meeting_info: MeetingInfo) -> None:
        if self._active is not None:
            return
        enriched = self.calendar_lookup.enrich(meeting_info)
        capture_session = create_session_paths(enriched.title or enriched.app)
        recording_handle = await asyncio.to_thread(
            self.recorder.start,
            capture_session,
            enriched.pid,
        )
        self._active = ActiveMeeting(
            meeting_info=enriched,
            capture_session=capture_session,
            recording_handle=recording_handle,
        )

    async def handle_meeting_end(self, meeting_info: MeetingInfo) -> PipelineJob | None:
        if self._active is None:
            return None
        active = self._active
        self._active = None
        await asyncio.to_thread(self.recorder.stop, active.recording_handle)
        job = PipelineJob(
            session_id=active.capture_session.session_id,
            app_audio_path=active.capture_session.app_audio_path,
            mic_audio_path=active.capture_session.mic_audio_path,
            meeting_info=active.meeting_info,
        )
        await self.queue.enqueue(job)
        return job
