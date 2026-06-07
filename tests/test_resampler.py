import numpy as np

from mt_linux.audio.resampler import resample_mono


def test_resample_mono_changes_length_for_new_rate():
    audio = np.arange(8, dtype=float)
    result = resample_mono(audio, source_rate=8, target_rate=4)
    assert len(result) == 4
