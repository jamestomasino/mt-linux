from __future__ import annotations

from mt_linux.diarization.diarizer import DiarizationSegment
from mt_linux.models import TranscriptSegment


REMOTE_SPEAKER_LABEL = "SPEAKER_REMOTE"
MIC_SPEAKER_LABEL = "MIC_SPEAKER"


def relabel_segments(
    segments: list[TranscriptSegment],
    *,
    speaker: str,
    track: str,
) -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            start=segment.start,
            end=segment.end,
            text=segment.text.strip(),
            speaker=speaker,
            confidence=segment.confidence,
            track=track,
        )
        for segment in segments
        if segment.text.strip()
    ]


def merge_track_segments(*groups: list[TranscriptSegment]) -> list[TranscriptSegment]:
    merged = [segment for group in groups for segment in group if segment.text.strip()]
    return sorted(merged, key=lambda segment: (segment.start, 0 if segment.track == "mic" else 1, segment.end))


def assign_speakers_by_overlap(
    transcript_segments: list[TranscriptSegment],
    diarization_segments: list[DiarizationSegment],
) -> list[TranscriptSegment]:
    if not diarization_segments:
        return transcript_segments
    for transcript in transcript_segments:
        best_speaker = transcript.speaker
        best_overlap = 0.0
        for diarized in diarization_segments:
            overlap = min(transcript.end, diarized.end) - max(transcript.start, diarized.start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = diarized.speaker
        if best_overlap > 0:
            transcript.speaker = best_speaker
    return transcript_segments
