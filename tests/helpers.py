from __future__ import annotations

from pathlib import Path
import struct
import wave


def write_test_wav(path: Path, seconds: int = 2, sample_rate: int = 16000) -> Path:
    frame_count = seconds * sample_rate
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = b"".join(struct.pack("<h", 1000 if i % 2 == 0 else -1000) for i in range(frame_count))
        handle.writeframes(frames)
    return path
