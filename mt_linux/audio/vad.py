from __future__ import annotations

import numpy as np


def trim_silence(
    samples: np.ndarray,
    sample_rate: int,
    threshold: float = 0.01,
    min_silence_seconds: float = 0.25,
) -> tuple[np.ndarray, int, int]:
    if samples.size == 0:
        return samples, 0, 0
    window = max(int(sample_rate * min_silence_seconds), 1)
    mask = np.abs(samples) >= threshold
    active_indices = np.flatnonzero(mask)
    if active_indices.size == 0:
        return samples[:0], 0, len(samples)
    start = max(int(active_indices[0]) - window, 0)
    end = min(int(active_indices[-1]) + window + 1, len(samples))
    return samples[start:end], start, end
