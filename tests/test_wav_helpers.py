from pathlib import Path

from mt_linux.audio.wav import (
    extract_wav_clip,
    mix_wav_files,
    wav_duration_minutes,
    wav_duration_seconds,
    wav_files_identical,
)
from tests.helpers import write_test_wav


def test_wav_helpers_measure_and_extract_clip(tmp_path: Path):
    source = write_test_wav(tmp_path / "source.wav", seconds=2)
    assert wav_duration_seconds(source) == 2.0
    assert wav_duration_minutes(source) == 1
    clip = extract_wav_clip(source, tmp_path / "clip.wav", 0.5, 1.5)
    assert clip.exists()
    assert wav_duration_seconds(clip) == 1.0


def test_wav_helpers_detect_identical_files_and_mix_tracks(tmp_path: Path):
    left = write_test_wav(tmp_path / "left.wav", seconds=1, amplitude=200)
    same = tmp_path / "same.wav"
    same.write_bytes(left.read_bytes())
    right = write_test_wav(tmp_path / "right.wav", seconds=1, amplitude=600)

    assert wav_files_identical(left, same) is True
    assert wav_files_identical(left, right) is False

    mixed = mix_wav_files(left, right, tmp_path / "mixed.wav")
    assert mixed.exists()
    assert wav_duration_seconds(mixed) == 1.0
