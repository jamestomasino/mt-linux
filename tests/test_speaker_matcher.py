from pathlib import Path

import numpy as np

from mt_linux.diarization.speaker_matcher import SpeakerMatcher


def test_speaker_matcher_updates_and_matches_profiles(tmp_path: Path):
    matcher = SpeakerMatcher(tmp_path / "speakers.json", similarity_threshold=0.8)
    vector = np.array([1.0, 0.0], dtype=float)
    matcher.update_profile("Alice Smith", vector)
    match = matcher.match_embedding(vector)
    assert match is not None
    assert match[0] == "Alice Smith"
