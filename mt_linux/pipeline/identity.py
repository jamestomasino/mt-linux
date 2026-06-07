from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import contextlib

from mt_linux.audio.wav import extract_wav_clip
from mt_linux.config import AppConfig
from mt_linux.diarization.diarizer import DiarizationSegment
from mt_linux.diarization.speaker_matcher import SpeakerMatcher
from mt_linux.models import ReviewEntry, SpeakerIdentity
from mt_linux.paths import REVIEW_SAMPLES_DIR, ensure_directories
from mt_linux.pipeline.job import PipelineJob
from mt_linux.pipeline.review_queue import ReviewQueue


def resolve_identities(
    config: AppConfig,
    diarization_segments: list[DiarizationSegment],
    transcript_path: Path | None = None,
    review_queue: ReviewQueue | None = None,
    job: PipelineJob | None = None,
    source_audio_path: Path | None = None,
    speaker_matcher: SpeakerMatcher | None = None,
) -> list[SpeakerIdentity]:
    if not diarization_segments:
        return [
            SpeakerIdentity(
                label="SPEAKER_00",
                name=config.speakers.mic_speaker_name or "SPEAKER_00",
                confidence="mic_track" if config.speakers.mic_speaker_name else "unidentified",
                review_queued=not bool(config.speakers.mic_speaker_name),
            )
        ]

    identities: list[SpeakerIdentity] = []
    by_speaker: dict[str, list[DiarizationSegment]] = defaultdict(list)
    for segment in diarization_segments:
        by_speaker[segment.speaker].append(segment)

    for speaker, segments in sorted(by_speaker.items()):
        best_segment = max(segments, key=lambda item: item.end - item.start)
        identity = SpeakerIdentity(
            label=speaker,
            name=speaker,
            confidence="unidentified",
            review_queued=True,
        )
        sample_path = None
        if source_audio_path and source_audio_path.exists():
            sample_path = _sample_path_for(job.session_id if job else "sample", speaker)
            extract_wav_clip(source_audio_path, sample_path, best_segment.start, best_segment.end)
        matched = _match_speaker(sample_path, speaker_matcher)
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
        if identity.review_queued and review_queue and transcript_path and job and sample_path and sample_path.exists():
            attendees = []
            if job.meeting_info.calendar_event:
                attendees = [attendee.display() for attendee in job.meeting_info.calendar_event.attendees]
            review_queue.add(
                ReviewEntry(
                    session_id=job.session_id,
                    speaker_label=speaker,
                    sample_path=sample_path,
                    calendar_attendees=attendees,
                    meeting_title=job.meeting_info.title,
                    meeting_date=job.meeting_info.start_time.date(),
                    transcript_path=transcript_path,
                )
            )
        elif sample_path and sample_path.exists():
            sample_path.unlink()
    return identities


def assign_speakers_to_transcript(
    transcript_segments,
    diarization_segments: list[DiarizationSegment],
):
    if not diarization_segments:
        return transcript_segments
    for transcript in transcript_segments:
        for diarized in diarization_segments:
            if transcript.start >= diarized.start and transcript.end <= diarized.end:
                transcript.speaker = diarized.speaker
                break
    return transcript_segments


def _sample_path_for(session_id: str, speaker_label: str) -> Path:
    ensure_directories()
    return REVIEW_SAMPLES_DIR / f"{session_id}_{speaker_label}.wav"


def _match_speaker(
    sample_path: Path | None,
    speaker_matcher: SpeakerMatcher | None,
) -> tuple[str, float, object] | None:
    if sample_path is None or speaker_matcher is None or not sample_path.exists():
        return None
    with contextlib.suppress(RuntimeError):
        embedding = speaker_matcher.embed_wav(sample_path)
        match = speaker_matcher.match_embedding(embedding)
        if match is not None:
            return match[0], match[1], embedding
    return None
