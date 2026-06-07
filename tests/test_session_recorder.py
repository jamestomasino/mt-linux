from pathlib import Path

from mt_linux.audio.capture import CaptureSession
from mt_linux.audio.processes import RecordingProcess
from mt_linux.audio.session_recorder import PipeWireRecordingHandle, PipeWireSessionRecorder


class _FakeProc:
    def poll(self):
        return None


def test_pipewire_session_recorder_starts_and_stops(monkeypatch, tmp_path: Path):
    calls = {"route": [], "start": [], "stop": [], "unload": []}

    monkeypatch.setattr(
        "mt_linux.audio.session_recorder.create_virtual_sink",
        lambda sink_name: (f"{sink_name}.monitor", "module-1"),
    )
    monkeypatch.setattr(
        "mt_linux.audio.session_recorder.route_app_to_sink",
        lambda pid, sink_name: calls["route"].append((pid, sink_name)),
    )

    def fake_start(command, output_path, kind):
        calls["start"].append((command, output_path, kind))
        return RecordingProcess(kind=kind, output_path=output_path, process=_FakeProc())

    monkeypatch.setattr("mt_linux.audio.session_recorder.start_recording_process", fake_start)
    monkeypatch.setattr(
        "mt_linux.audio.session_recorder.stop_recording_process",
        lambda process: calls["stop"].append(process.kind),
    )
    monkeypatch.setattr(
        "mt_linux.audio.session_recorder.unload_module",
        lambda module_id: calls["unload"].append(module_id),
    )

    recorder = PipeWireSessionRecorder(recorder_executable="pw-record", mic_device_name="default-mic")
    session = CaptureSession(
        session_id="session-1",
        app_audio_path=tmp_path / "app.wav",
        mic_audio_path=tmp_path / "mic.wav",
    )
    handle = recorder.start(session, app_pid=4242)
    assert isinstance(handle, PipeWireRecordingHandle)
    assert calls["route"] == [(4242, "mt-linux-session-1")]
    assert calls["start"][0][2] == "app"
    assert calls["start"][1][2] == "mic"

    recorder.stop(handle)
    assert calls["stop"] == ["app", "mic"]
    assert calls["unload"] == ["module-1"]
