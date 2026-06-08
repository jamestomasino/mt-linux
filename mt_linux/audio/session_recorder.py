from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import wave

from mt_linux.audio.capture import CaptureSession
from mt_linux.audio.commands import build_default_mic_record_command, build_source_record_command
from mt_linux.audio.pulse import get_preferred_system_capture_source_name
from mt_linux.audio.processes import RecordingProcess, start_recording_process, stop_recording_process


@dataclass
class RecordingHandle:
    session: CaptureSession


@dataclass
class PipeWireRecordingHandle(RecordingHandle):
    system_source_name: str
    app_process: RecordingProcess
    mic_process: RecordingProcess


class SessionRecorder(ABC):
    @abstractmethod
    def start(self, session: CaptureSession, app_pid: int) -> RecordingHandle:
        raise NotImplementedError

    @abstractmethod
    def stop(self, handle: RecordingHandle) -> None:
        raise NotImplementedError


class PlaceholderRecorder(SessionRecorder):
    def start(self, session: CaptureSession, app_pid: int) -> RecordingHandle:
        _create_empty_wav(session.app_audio_path)
        _create_empty_wav(session.mic_audio_path)
        return RecordingHandle(session=session)

    def stop(self, handle: RecordingHandle) -> None:
        return None


def _create_empty_wav(path: Path, sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"")


class PipeWireSessionRecorder(SessionRecorder):
    def __init__(
        self,
        recorder_executable: str = "pw-record",
        sample_rate: int = 16000,
        mic_device_name: str = "",
        system_source_name: str = "",
    ):
        self.recorder_executable = recorder_executable
        self.sample_rate = sample_rate
        self.mic_device_name = mic_device_name
        self.system_source_name = system_source_name

    def start(self, session: CaptureSession, app_pid: int) -> PipeWireRecordingHandle:
        monitor_source = get_preferred_system_capture_source_name(
            app_pid,
            explicit_source_name=self.system_source_name,
        )
        app_command = build_source_record_command(
            self.recorder_executable,
            monitor_source,
            session.app_audio_path,
            sample_rate=self.sample_rate,
        )
        mic_command = build_default_mic_record_command(
            self.recorder_executable,
            session.mic_audio_path,
            sample_rate=self.sample_rate,
            device_name=self.mic_device_name,
        )
        app_process = start_recording_process(app_command, session.app_audio_path, "app")
        mic_process = start_recording_process(mic_command, session.mic_audio_path, "mic")
        return PipeWireRecordingHandle(
            session=session,
            system_source_name=monitor_source,
            app_process=app_process,
            mic_process=mic_process,
        )

    def stop(self, handle: RecordingHandle) -> None:
        if not isinstance(handle, PipeWireRecordingHandle):
            return
        try:
            stop_recording_process(handle.app_process)
        finally:
            stop_recording_process(handle.mic_process)
