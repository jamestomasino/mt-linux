from __future__ import annotations

from pathlib import Path
import wave


def wav_duration_seconds(path: Path) -> float:
    if path.suffix.lower() != ".wav":
        return 0.0
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
    return frames / max(rate, 1)


def wav_duration_minutes(path: Path) -> int:
    seconds = wav_duration_seconds(path)
    if seconds <= 0:
        return 0
    return max(int(seconds // 60), 1)


def extract_wav_clip(source: Path, target: Path, start_seconds: float, end_seconds: float) -> Path:
    with wave.open(str(source), "rb") as src:
        params = src.getparams()
        frame_rate = src.getframerate()
        start_frame = max(int(start_seconds * frame_rate), 0)
        end_frame = max(int(end_seconds * frame_rate), start_frame)
        src.setpos(min(start_frame, src.getnframes()))
        frames = src.readframes(end_frame - start_frame)
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as dst:
        dst.setparams(params)
        dst.writeframes(frames)
    return target
