from __future__ import annotations

from pathlib import Path
import wave

import numpy as np

from mt_linux.audio.resampler import resample_mono


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


def wav_files_identical(left: Path, right: Path) -> bool:
    if left.resolve() == right.resolve():
        return True
    if not left.exists() or not right.exists() or left.stat().st_size != right.stat().st_size:
        return False
    return left.read_bytes() == right.read_bytes()


def mix_wav_files(left: Path, right: Path, target: Path, target_rate: int = 16000) -> Path:
    left_samples = _read_wav_mono(left, target_rate=target_rate)
    right_samples = _read_wav_mono(right, target_rate=target_rate)
    length = max(len(left_samples), len(right_samples))
    left_padded = _pad_samples(left_samples, length)
    right_padded = _pad_samples(right_samples, length)
    mixed = np.clip((left_padded + right_padded) / 2.0, -1.0, 1.0)
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(target_rate)
        handle.writeframes((mixed * 32767.0).astype(np.int16).tobytes())
    return target


def _read_wav_mono(path: Path, target_rate: int) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        frame_rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    dtype = _sample_dtype(sample_width)
    samples = np.frombuffer(frames, dtype=dtype).astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    scale = float(max(np.iinfo(dtype).max, 1))
    normalized = np.clip(samples / scale, -1.0, 1.0)
    return resample_mono(normalized, source_rate=frame_rate, target_rate=target_rate)


def _sample_dtype(sample_width: int):
    if sample_width == 1:
        return np.int8
    if sample_width == 2:
        return np.int16
    if sample_width == 4:
        return np.int32
    raise ValueError(f"Unsupported WAV sample width: {sample_width}")


def _pad_samples(samples: np.ndarray, target_length: int) -> np.ndarray:
    if len(samples) >= target_length:
        return samples[:target_length]
    return np.pad(samples, (0, target_length - len(samples)))
