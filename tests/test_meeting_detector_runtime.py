import json
import subprocess

import psutil

from mt_linux.detection.meeting_detector import get_active_meeting_pid


class _FakeProc:
    def __init__(self, pid: int, name: str):
        self.info = {"pid": pid, "name": name}


def test_get_active_meeting_pid_detects_teams_audio_service(monkeypatch):
    monkeypatch.setattr(
        psutil,
        "process_iter",
        lambda attrs: [
            _FakeProc(1392556, "teams-for-linux"),
            _FakeProc(1392812, "teams-for-linux"),
        ],
    )
    payload = [
        {
            "index": 32938,
            "corked": False,
            "properties": {
                "application.process.id": "1392812",
            },
        }
    ]
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )
    assert get_active_meeting_pid() == ("teams", 1392812, 32938)


def test_get_active_meeting_pid_ignores_non_meeting_processes(monkeypatch):
    monkeypatch.setattr(
        psutil,
        "process_iter",
        lambda attrs: [_FakeProc(1234, "audacious")],
    )
    assert get_active_meeting_pid() is None


def test_get_active_meeting_pid_ignores_corked_sink_inputs(monkeypatch):
    monkeypatch.setattr(
        psutil,
        "process_iter",
        lambda attrs: [_FakeProc(1392812, "teams-for-linux")],
    )
    payload = [
        {
            "index": 32938,
            "corked": True,
            "properties": {
                "application.process.id": "1392812",
            },
        }
    ]
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )
    assert get_active_meeting_pid() is None
