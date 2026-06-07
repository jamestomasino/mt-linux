from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass
class RecordingProcess:
    kind: str
    output_path: Path
    process: subprocess.Popen


def start_recording_process(command: list[str], output_path: Path, kind: str) -> RecordingProcess:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return RecordingProcess(kind=kind, output_path=output_path, process=process)


def stop_recording_process(recording_process: RecordingProcess, timeout_seconds: float = 5.0) -> None:
    if recording_process.process.poll() is not None:
        return
    recording_process.process.terminate()
    try:
        recording_process.process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        recording_process.process.kill()
        recording_process.process.wait(timeout=timeout_seconds)
