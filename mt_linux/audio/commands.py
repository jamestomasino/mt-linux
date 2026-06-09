from __future__ import annotations

from pathlib import Path
import shutil


def detect_recording_command() -> str | None:
    for candidate in ("parecord", "pw-record"):
        if shutil.which(candidate):
            return candidate
    return None


def build_source_record_command(
    executable: str,
    source_name: str,
    output_path: Path,
    sample_rate: int = 16000,
) -> list[str]:
    if executable == "pw-record":
        return [
            executable,
            "--target",
            source_name,
            "--rate",
            str(sample_rate),
            "--channels",
            "1",
            str(output_path),
        ]
    if executable == "parecord":
        return [
            executable,
            "--device",
            source_name,
            "--rate",
            str(sample_rate),
            "--channels",
            "1",
            "--file-format=wav",
            str(output_path),
        ]
    raise ValueError(f"Unsupported recorder executable: {executable}")


def build_default_mic_record_command(
    executable: str,
    output_path: Path,
    sample_rate: int = 16000,
    device_name: str = "",
) -> list[str]:
    target = device_name.strip()
    if executable == "pw-record":
        command = [executable]
        if target:
            command.extend(["--target", target])
        command.extend(
            [
                "--rate",
                str(sample_rate),
                "--channels",
                "1",
                str(output_path),
            ]
        )
        return command
    if executable == "parecord":
        command = [executable]
        if target:
            command.extend(["--device", target])
        command.extend(
            [
                "--rate",
                str(sample_rate),
                "--channels",
                "1",
                "--file-format=wav",
                str(output_path),
            ]
        )
        return command
    raise ValueError(f"Unsupported recorder executable: {executable}")
