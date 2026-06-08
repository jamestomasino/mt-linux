import json
import subprocess

import psutil

from mt_linux.detection.meeting_detector import get_active_meeting_pid


class _FakeProc:
    def __init__(self, pid: int, name: str):
        self.info = {"pid": pid, "name": name}


def test_get_active_meeting_pid_detects_slack_audio_service(monkeypatch):
    monkeypatch.setattr(
        psutil,
        "process_iter",
        lambda attrs: [
            _FakeProc(1392312, "slack"),
            _FakeProc(1392507, "slack"),
        ],
    )
    payload = [
        {
            "info": {
                "props": {
                    "application.process.id": "1392507",
                    "media.class": "Stream/Output/Audio",
                }
            }
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
    assert get_active_meeting_pid() == ("slack", 1392507)


def test_get_active_meeting_pid_ignores_non_meeting_processes(monkeypatch):
    monkeypatch.setattr(
        psutil,
        "process_iter",
        lambda attrs: [_FakeProc(1234, "audacious")],
    )
    assert get_active_meeting_pid() is None
