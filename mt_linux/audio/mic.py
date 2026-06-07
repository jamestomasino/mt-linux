from __future__ import annotations

from pathlib import Path
import wave


def record_mic(output_path: Path, sample_rate: int = 16000, seconds: int = 5) -> None:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError(
            "sounddevice is not installed. Install the audio extras to enable microphone capture."
        ) from exc
    with sd.RawInputStream(samplerate=sample_rate, channels=1, dtype="int16") as stream:
        with wave.open(str(output_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            frame_count = (sample_rate * seconds) // 1024
            for _ in range(frame_count):
                data, _overflowed = stream.read(1024)
                handle.writeframes(data)
