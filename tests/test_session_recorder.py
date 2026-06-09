from pathlib import Path

from mt_linux.audio.capture import CaptureSession
from mt_linux.audio.processes import RecordingProcess
from mt_linux.audio.session_recorder import PipeWireRecordingHandle, PipeWireSessionRecorder


class _FakeProc:
    def __init__(self, pid=123):
        self.pid = pid

    def poll(self):
        return None


def test_pipewire_session_recorder_starts_and_stops(monkeypatch, tmp_path: Path):
    calls = {"start": [], "stop": [], "bind": []}
    monkeypatch.setattr(
        "mt_linux.audio.session_recorder.get_preferred_system_capture_source_name",
        lambda app_pid, explicit_source_name="": "bluez_output.AC_80_0A_14_01_9F.1.monitor",
    )
    monkeypatch.setattr(
        "mt_linux.audio.session_recorder.get_mic_capture_source_name",
        lambda explicit_source_name="": "easyeffects_source",
    )

    def fake_start(command, output_path, kind):
        calls["start"].append((command, output_path, kind))
        pid = 100 if kind == "app" else 101
        return RecordingProcess(kind=kind, output_path=output_path, process=_FakeProc(pid=pid))

    monkeypatch.setattr("mt_linux.audio.session_recorder.start_recording_process", fake_start)
    monkeypatch.setattr(
        "mt_linux.audio.session_recorder.bind_recording_process_to_source",
        lambda pid, source: calls["bind"].append((pid, source)),
    )
    monkeypatch.setattr(
        "mt_linux.audio.session_recorder.stop_recording_process",
        lambda process: calls["stop"].append(process.kind),
    )

    recorder = PipeWireSessionRecorder(recorder_executable="parecord", mic_device_name="easyeffects_source")
    session = CaptureSession(
        session_id="session-1",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
    )
    handle = recorder.start(session, app_pid=4242)
    assert isinstance(handle, PipeWireRecordingHandle)
    assert handle.system_source_name == "bluez_output.AC_80_0A_14_01_9F.1.monitor"
    assert handle.mic_source_name == "easyeffects_source"
    assert calls["start"][0][2] == "app"
    assert calls["start"][1][2] == "mic"
    assert "bluez_output.AC_80_0A_14_01_9F.1.monitor" in calls["start"][0][0]
    assert "easyeffects_source" in calls["start"][1][0]
    assert calls["bind"] == [
        (100, "bluez_output.AC_80_0A_14_01_9F.1.monitor"),
        (101, "easyeffects_source"),
    ]

    recorder.stop(handle)
    assert calls["stop"] == ["app", "mic"]
