from __future__ import annotations

import logging

from mt_linux.audio.commands import detect_recording_command
from mt_linux.audio.session_recorder import PipeWireSessionRecorder, PlaceholderRecorder, SessionRecorder
from mt_linux.config import AudioConfig


def create_session_recorder(config: AudioConfig) -> SessionRecorder:
    command = detect_recording_command()
    if config.app_audio_backend == "pipewire" and command:
        return PipeWireSessionRecorder(
            recorder_executable=command,
            sample_rate=16000,
            mic_device_name=config.mic_device_name,
        )
    logging.warning("No PipeWire recorder command available; using placeholder recorder.")
    return PlaceholderRecorder()
