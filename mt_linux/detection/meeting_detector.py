from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import subprocess
import threading
import time

import psutil

from mt_linux.detection.activity_state import MeetingActivityState
from mt_linux.models import MeetingInfo


MEETING_PROCESS_NAMES = {
    "zoom": "zoom",
    "zoom.real": "zoom",
    "teams-for-linux": "teams",
}


@dataclass
class DetectorCallbacks:
    on_meeting_start: Callable[[MeetingInfo], None]
    on_meeting_end: Callable[[MeetingInfo], None]


class PipeWireActivityPoller:
    def __init__(
        self,
        poll_interval: int,
        callbacks: DetectorCallbacks,
        grace_period_seconds: int = 5,
        activity_gate: Callable[[str, int, int], bool] | None = None,
    ):
        self.poll_interval = poll_interval
        self.callbacks = callbacks
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._activity_state = MeetingActivityState(grace_period_seconds=grace_period_seconds)
        self._activity_gate = activity_gate

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            active = get_active_meeting_pid()
            if active is not None and self._activity_gate is not None:
                app, pid, stream_id = active
                if not self._activity_gate(app, pid, stream_id):
                    active = None
            transition = self._activity_state.update(active)
            if transition.ended:
                app, pid, stream_id = transition.ended
                self.callbacks.on_meeting_end(
                    MeetingInfo(
                        app=app,
                        pid=pid,
                        detection_method="pipewire",
                        start_time=datetime.now(UTC),
                        stream_id=stream_id,
                    )
                )
            if transition.started:
                app, pid, stream_id = transition.started
                self.callbacks.on_meeting_start(
                    MeetingInfo(
                        app=app,
                        pid=pid,
                        detection_method="pipewire",
                        start_time=datetime.now(UTC),
                        stream_id=stream_id,
                        title=None,
                    )
                )
            time.sleep(self.poll_interval)


class MeetingDetector:
    def __init__(
        self,
        on_meeting_start,
        on_meeting_end,
        poll_interval: int = 5,
        grace_period_seconds: int = 5,
        activity_gate: Callable[[str, int, int], bool] | None = None,
    ):
        callbacks = DetectorCallbacks(on_meeting_start=on_meeting_start, on_meeting_end=on_meeting_end)
        self._pipewire_poller = PipeWireActivityPoller(
            poll_interval,
            callbacks,
            grace_period_seconds=grace_period_seconds,
            activity_gate=activity_gate,
        )

    def start(self) -> None:
        self._pipewire_poller.start()

    def stop(self) -> None:
        self._pipewire_poller.stop()


def get_active_meeting_pid() -> tuple[str, int, int] | None:
    candidate_pids: dict[int, str] = {}
    for proc in psutil.process_iter(["name", "pid"]):
        name = proc.info.get("name")
        if not name:
            continue
        app = MEETING_PROCESS_NAMES.get(name)
        if app:
            candidate_pids[int(proc.info["pid"])] = app
    if not candidate_pids:
        return None
    result = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True, text=True, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        sink_inputs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    for item in sink_inputs:
        props = item.get("properties", {})
        pid = props.get("application.process.id")
        if pid is None:
            continue
        pid_int = int(pid)
        if item.get("corked"):
            continue
        if pid_int in candidate_pids:
            stream_id = int(item.get("index"))
            return candidate_pids[pid_int], pid_int, stream_id
    return None
