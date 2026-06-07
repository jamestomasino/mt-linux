from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re

from mt_linux.paths import DATA_DIR, ensure_directories


@dataclass
class CaptureSession:
    session_id: str
    app_audio_path: Path
    mic_audio_path: Path


def create_session_paths(title: str = "meeting") -> CaptureSession:
    ensure_directories()
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    session_id = f"{stamp}-{_safe_title(title)}"
    audio_dir = DATA_DIR / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    return CaptureSession(
        session_id=session_id,
        app_audio_path=audio_dir / f"{session_id}_app.wav",
        mic_audio_path=audio_dir / f"{session_id}_mic.wav",
    )


def _safe_title(title: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", title.strip().lower()).strip("-")
    return cleaned or "meeting"
