from pathlib import Path

from mt_linux.audio.capture import CaptureSession
from mt_linux.audio.processes import RecordingProcess
from mt_linux.audio.session_recorder import PipeWireRecordingHandle, PipeWireSessionRecorder


class _FakeProc:
    def poll(self):
        return None


def test_pipewire_session_recorder_starts_and_stops(monkeypatch, tmp_path: Path):
    calls = {"start": [], "stop": []}
    monkeypatch.setattr(
        "mt_linux.audio.session_recorder.get_preferred_system_capture_source_name",
        lambda app_pid, explicit_source_name="": "bluez_output.AC_80_0A_14_01_9F.1.monitor",
    )

    def fake_start(command, output_path, kind):
        calls["start"].append((command, output_path, kind))
        return RecordingProcess(kind=kind, output_path=output_path, process=_FakeProc())

    monkeypatch.setattr("mt_linux.audio.session_recorder.start_recording_process", fake_start)
    monkeypatch.setattr(
        "mt_linux.audio.session_recorder.stop_recording_process",
        lambda process: calls["stop"].append(process.kind),
    )

    recorder = PipeWireSessionRecorder(recorder_executable="pw-record", mic_device_name="default-mic")
    session = CaptureSession(
        session_id="session-1",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
    )
    handle = recorder.start(session, app_pid=4242)
    assert isinstance(handle, PipeWireRecordingHandle)
    assert handle.system_source_name == "bluez_output.AC_80_0A_14_01_9F.1.monitor"
    assert calls["start"][0][2] == "app"
    assert calls["start"][1][2] == "mic"
    assert "bluez_output.AC_80_0A_14_01_9F.1.monitor" in calls["start"][0][0]

    recorder.stop(handle)
    assert calls["stop"] == ["app", "mic"]
