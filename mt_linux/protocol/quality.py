from __future__ import annotations

import re

from mt_linux.models import TranscriptSegment


_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def has_substantive_transcript(
    segments: list[TranscriptSegment],
    *,
    min_word_count: int = 12,
    min_unique_words: int = 6,
    min_long_segments: int = 2,
) -> bool:
    words: list[str] = []
    long_segments = 0
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        segment_words = [word.lower() for word in _WORD_RE.findall(text) if len(word) >= 2]
        if len(segment_words) >= 4:
            long_segments += 1
        words.extend(segment_words)
    unique_words = set(words)
    return (
        len(words) >= min_word_count
        and len(unique_words) >= min_unique_words
        and long_segments >= min_long_segments
    )
