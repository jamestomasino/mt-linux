import asyncio
from datetime import UTC, datetime
from pathlib import Path

from mt_linux.audio.capture import CaptureSession
from mt_linux.audio.session_recorder import RecordingHandle, SessionRecorder
from mt_linux.config import CalendarConfig
from mt_linux.detection.calendar_lookup import CalendarLookupService
from mt_linux.models import Attendee, CalendarEvent, MeetingInfo
from mt_linux.pipeline.queue import PipelineQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore
from mt_linux.runtime.meeting_sessions import MeetingSessionManager


class _FakeRecorder(SessionRecorder):
    def __init__(self):
        self.started = []
        self.stopped = []

    def start(self, session: CaptureSession, app_pid: int) -> RecordingHandle:
        session.app_audio_path.parent.mkdir(parents=True, exist_ok=True)
        session.app_audio_path.write_bytes(b"")
        session.mic_audio_path.write_bytes(b"")
        self.started.append((session, app_pid))
        return RecordingHandle(session=session)

    def stop(self, handle: RecordingHandle) -> None:
        self.stopped.append(handle.session.session_id)


class _FakeCalendarLookup(CalendarLookupService):
    def __init__(self, event: CalendarEvent | None):
        super().__init__(CalendarConfig())
        self.event = event

    def enrich(self, meeting_info: MeetingInfo) -> MeetingInfo:
        if self.event is not None:
            meeting_info.calendar_event = self.event
            meeting_info.title = self.event.title
        return meeting_info


def test_meeting_session_manager_starts_and_enqueues_job(tmp_path: Path, monkeypatch):
    async def runner():
        queue = PipelineQueue(store=JobSnapshotStore(tmp_path / "jobs"))
        recorder = _FakeRecorder()
        event = CalendarEvent(
            event_id="event-1",
            title="Weekly Standup",
            start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
            end_time=datetime(2026, 6, 7, 15, 0, tzinfo=UTC),
            organizer="Alice Smith",
            attendees=[Attendee(name="Bob", email="bob@example.com")],
        )
        manager = MeetingSessionManager(
            queue=queue,
            calendar_lookup=_FakeCalendarLookup(event),
            recorder=recorder,
        )
        monkeypatch.setattr(
            "mt_linux.runtime.meeting_sessions.create_session_paths",
            lambda title: CaptureSession(
                session_id="session-1",
                app_audio_path=tmp_path / "audio" / "app.wav",
                mic_audio_path=tmp_path / "audio" / "mic.wav",
            ),
        )
        info = MeetingInfo(
            app="zoom",
            pid=321,
            detection_method="pipewire",
            start_time=datetime(2026, 6, 7, 14, 31, tzinfo=UTC),
        )
        await manager.handle_meeting_start(info)
        assert manager.active is not None
        assert manager.active.meeting_info.title == "Weekly Standup"

        job = await manager.handle_meeting_end(info)
        assert job is not None
        assert job.session_id == "session-1"
        assert job.meeting_info.calendar_event is not None
        assert recorder.stopped == ["session-1"]

        restored = queue.store.load_pending()
        assert len(restored) == 1
        assert restored[0].session_id == "session-1"

    asyncio.run(runner())
