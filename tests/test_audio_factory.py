from mt_linux.audio.factory import create_session_recorder
from mt_linux.audio.session_recorder import PipeWireSessionRecorder, PlaceholderRecorder
from mt_linux.config import AudioConfig


def test_audio_factory_uses_pipewire_recorder_when_command_exists(monkeypatch):
    monkeypatch.setattr("mt_linux.audio.factory.detect_recording_command", lambda: "parecord")
    recorder = create_session_recorder(AudioConfig())
    assert isinstance(recorder, PipeWireSessionRecorder)


def test_audio_factory_falls_back_to_placeholder_without_command(monkeypatch):
    monkeypatch.setattr("mt_linux.audio.factory.detect_recording_command", lambda: None)
    recorder = create_session_recorder(AudioConfig())
    assert isinstance(recorder, PlaceholderRecorder)
