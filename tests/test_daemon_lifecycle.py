import asyncio
from datetime import UTC, datetime, timedelta

from mt_linux.control import ControlResult
from mt_linux.daemon import DaemonState, MeetingLifecycleCoordinator
from mt_linux.models import MeetingInfo


class _FakeQueue:
    def snapshot(self):
        return {"jobs": [], "queued_jobs": ["session-2"]}


class _FakeSessionManager:
    def __init__(self):
        self.active = None
        self.started = []
        self.ended = []

    async def handle_meeting_start(self, info):
        self.started.append(info)
        self.active = type(
            "ActiveMeeting",
            (),
            {
                "capture_session": type("CaptureSession", (), {"session_id": "session-1"})(),
                "meeting_info": info,
            },
        )()

    async def handle_meeting_end(self, info):
        self.ended.append(info)
        self.active = None


def test_lifecycle_coordinator_emits_critical_notification_on_fast_handoff(monkeypatch):
    notices = []

    def _fake_notify(title, message, *, urgency="normal"):
        notices.append((title, message, urgency))

    manager = _FakeSessionManager()
    state = DaemonState(_FakeQueue(), manager)
    state.last_control_result = ControlResult(request_id="req-1", status="ok", message="ok")
    coordinator = MeetingLifecycleCoordinator(manager, state, handoff_window_seconds=30)
    monkeypatch.setattr("mt_linux.daemon.notify", _fake_notify)
    monkeypatch.setattr(state, "write", lambda: None)

    async def runner():
        await coordinator.handle_meeting_start(
            MeetingInfo(
                app="zoom",
                pid=101,
                detection_method="pipewire",
                start_time=datetime(2026, 6, 10, 10, 0, tzinfo=UTC),
                title="Arg CMS Social Listening Report IR",
            )
        )
        await coordinator.handle_meeting_end(
            MeetingInfo(
                app="zoom",
                pid=101,
                detection_method="pipewire",
                start_time=datetime(2026, 6, 10, 10, 29, tzinfo=UTC),
            )
        )
        coordinator._last_ended_at = datetime.now(UTC) - timedelta(seconds=5)
        await coordinator.handle_meeting_start(
            MeetingInfo(
                app="teams",
                pid=202,
                detection_method="pipewire",
                start_time=datetime(2026, 6, 10, 10, 30, tzinfo=UTC),
                title="Introductory meeting with Lauren",
            )
        )

    asyncio.run(runner())

    assert notices == [
        (
            "Meeting Transcriber",
            "Meeting changed: Arg CMS Social Listening Report IR -> Introductory meeting with Lauren",
            "critical",
        )
    ]
