import numpy as np

from mt_linux.audio.vad import trim_silence


def test_trim_silence_trims_leading_and_trailing_quiet_sections():
    audio = np.array([0.0, 0.0, 0.02, 0.03, 0.02, 0.0, 0.0], dtype=float)
    trimmed, start, end = trim_silence(audio, sample_rate=4, threshold=0.01, min_silence_seconds=0.25)
    assert start == 1
    assert end == 6
    assert np.allclose(trimmed, np.array([0.0, 0.02, 0.03, 0.02, 0.0]))
