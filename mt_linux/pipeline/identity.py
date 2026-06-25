from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import contextlib

from mt_linux.audio.wav import extract_wav_clip
from mt_linux.config import AppConfig
from mt_linux.diarization.diarizer import DiarizationSegment
from mt_linux.diarization.speaker_matcher import SpeakerMatcher
from mt_linux.models import ReviewEntry, SpeakerIdentity, TranscriptSegment
from mt_linux.paths import REVIEW_SAMPLES_DIR, ensure_directories
from mt_linux.pipeline.job import PipelineJob
from mt_linux.pipeline.review_queue import ReviewQueue
from mt_linux.pipeline.transcript_tracks import MIC_SPEAKER_LABEL, assign_speakers_by_overlap


def resolve_identities(
    config: AppConfig,
    transcript_segments: list[TranscriptSegment],
    diarization_segments: list[DiarizationSegment],
    transcript_path: Path | None = None,
    review_queue: ReviewQueue | None = None,
    job: PipelineJob | None = None,
    source_audio_path: Path | None = None,
    speaker_matcher: SpeakerMatcher | None = None,
) -> list[SpeakerIdentity]:
    identities: list[SpeakerIdentity] = []
    by_speaker: dict[str, list[TranscriptSegment]] = defaultdict(list)
    for segment in transcript_segments:
        if segment.text.strip():
            by_speaker[segment.speaker].append(segment)

    if not by_speaker:
        return [
            SpeakerIdentity(
                label=MIC_SPEAKER_LABEL,
                name=config.speakers.mic_speaker_name or MIC_SPEAKER_LABEL,
                confidence="mic_track" if config.speakers.mic_speaker_name else "unidentified",
                review_queued=not bool(config.speakers.mic_speaker_name),
            )
        ]

    for speaker, segments in sorted(by_speaker.items()):
        if _is_mic_speaker(speaker, config):
            identities.append(
                SpeakerIdentity(
                    label=speaker,
                    name=config.speakers.mic_speaker_name or speaker,
                    confidence="mic_track" if config.speakers.mic_speaker_name else "unidentified",
                    review_queued=not bool(config.speakers.mic_speaker_name),
                )
            )
            continue

        identity = SpeakerIdentity(
            label=speaker,
            name=speaker,
            confidence="unidentified",
            review_queued=True,
        )

        # Extract multiple sample clips for this speaker.
        sample_paths: list[Path] = []
        max_samples = getattr(config.speakers, "max_samples_per_speaker", 3)
        best_segments = _best_sample_segments(speaker, segments, diarization_segments, max_samples)
        if source_audio_path and source_audio_path.exists():
            for idx, seg in enumerate(best_segments):
                clip_path = _sample_path_for(job.session_id if job else "sample", speaker, idx)
                extract_wav_clip(source_audio_path, clip_path, seg.start, seg.end)
                sample_paths.append(clip_path)

        # Match using averaged embedding from all samples.
        matched = _match_speaker(sample_paths, speaker_matcher)
        if matched is not None:
            matched_name, similarity, embedding = matched
            identity = SpeakerIdentity(
                label=speaker,
                name=matched_name,
                confidence="voice_profile",
                similarity=similarity,
                review_queued=False,
            )
            if speaker_matcher is not None and embedding is not None:
                speaker_matcher.update_profile(matched_name, embedding)
        identities.append(identity)
        if identity.review_queued and review_queue and transcript_path and job and sample_paths:
            # Use the first sample for the review entry.
            first_sample = sample_paths[0]
            if first_sample.exists():
                attendees = []
                if job.meeting_info.calendar_event:
                    attendees = [attendee.display() for attendee in job.meeting_info.calendar_event.attendees]
                review_queue.add(
                    ReviewEntry(
                        session_id=job.session_id,
                        speaker_label=speaker,
                        sample_path=first_sample,
                        calendar_attendees=attendees,
                        meeting_title=job.meeting_info.title,
                        meeting_date=job.meeting_info.start_time.date(),
                        transcript_path=transcript_path,
                    )
                )
        elif sample_paths:
            for sp in sample_paths:
                if sp.exists():
                    sp.unlink()
    return identities


def assign_speakers_to_transcript(
    transcript_segments: list[TranscriptSegment],
    diarization_segments: list[DiarizationSegment],
):
    return assign_speakers_by_overlap(transcript_segments, diarization_segments)


def _sample_path_for(session_id: str, speaker_label: str, index: int = 0) -> Path:
    ensure_directories()
    return REVIEW_SAMPLES_DIR / f"{session_id}_{speaker_label}_{index}.wav"


def _match_speaker(
    sample_paths: list[Path],
    speaker_matcher: SpeakerMatcher | None,
) -> tuple[str, float, object] | None:
    if not sample_paths or speaker_matcher is None:
        return None
    valid = [p for p in sample_paths if p.exists()]
    if not valid:
        return None
    with contextlib.suppress(RuntimeError):
        if len(valid) > 1:
            embedding = speaker_matcher.embed_multiple(valid)
        else:
            embedding = speaker_matcher.embed_wav(valid[0])
        if embedding is None:
            return None
        match = speaker_matcher.match_embedding(embedding)
        if match is not None:
            return match[0], match[1], embedding
    return None


# Minimum duration (seconds) for a sample clip to be considered valid.
_MIN_SAMPLE_DURATION = 1.5


def _best_sample_segments(
    speaker: str,
    transcript_segments: list[TranscriptSegment],
    diarization_segments: list[DiarizationSegment],
    max_samples: int = 3,
):
    """Pick the longest diarization segments for a speaker, filtering out clips that are too short."""
    diarized = [segment for segment in diarization_segments if segment.speaker == speaker]
    if diarized:
        # Sort by duration descending, filter out clips shorter than minimum.
        good = [s for s in diarized if (s.end - s.start) >= _MIN_SAMPLE_DURATION]
        return sorted(good, key=lambda item: item.end - item.start, reverse=True)[:max_samples]
    good = [s for s in transcript_segments if (s.end - s.start) >= _MIN_SAMPLE_DURATION]
    return sorted(good, key=lambda item: item.end - item.start, reverse=True)[:max_samples]


def _is_mic_speaker(speaker: str, config: AppConfig) -> bool:
    return speaker in {MIC_SPEAKER_LABEL, config.speakers.mic_speaker_name}
