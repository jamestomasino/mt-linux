from pathlib import Path

from mt_linux.audio.wav import extract_wav_clip, wav_duration_minutes, wav_duration_seconds
from tests.helpers import write_test_wav


def test_wav_helpers_measure_and_extract_clip(tmp_path: Path):
    source = write_test_wav(tmp_path / "source.wav", seconds=2)
    assert wav_duration_seconds(source) == 2.0
    assert wav_duration_minutes(source) == 1
    clip = extract_wav_clip(source, tmp_path / "clip.wav", 0.5, 1.5)
    assert clip.exists()
    assert wav_duration_seconds(clip) == 1.0
