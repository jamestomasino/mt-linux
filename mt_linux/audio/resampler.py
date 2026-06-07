from __future__ import annotations

import numpy as np


def resample_mono(samples: np.ndarray, source_rate: int, target_rate: int = 16000) -> np.ndarray:
    if source_rate == target_rate:
        return samples.astype(np.float32)
    duration = len(samples) / source_rate
    target_length = max(int(duration * target_rate), 1)
    source_positions = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
    target_positions = np.linspace(0.0, 1.0, num=target_length, endpoint=False)
    return np.interp(target_positions, source_positions, samples).astype(np.float32)
