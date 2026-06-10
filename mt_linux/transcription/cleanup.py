from __future__ import annotations

import re

from mt_linux.models import TranscriptSegment


_MIC_HALLUCINATION_PHRASES = {
    "thank you",
    "thanks",
    "amen",
}


def suppress_low_signal_segments(
    segments: list[TranscriptSegment],
    *,
    track: str,
) -> list[TranscriptSegment]:
    if track != "mic":
        return [segment for segment in segments if segment.text.strip()]
    return [segment for segment in segments if not _should_drop_mic_segment(segment)]


def _should_drop_mic_segment(segment: TranscriptSegment) -> bool:
    text = segment.text.strip()
    if not text:
        return True
    normalized = _normalize_text(text)
    if not normalized:
        return True
    word_count = len(normalized.split())
    low_confidence = segment.confidence is not None and segment.confidence <= -0.8
    likely_no_speech = segment.no_speech_prob is not None and segment.no_speech_prob >= 0.5
    if _is_punctuation_only(text):
        return True
    if normalized in _MIC_HALLUCINATION_PHRASES and (likely_no_speech or low_confidence or word_count <= 2):
        return True
    if word_count <= 2 and likely_no_speech and low_confidence:
        return True
    return False


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", text.lower())).strip()


def _is_punctuation_only(text: str) -> bool:
    return not re.search(r"\w", text)
