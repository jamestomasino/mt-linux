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
        sample_path = None
        best_segment = _best_sample_segment(speaker, segments, diarization_segments)
        if source_audio_path and source_audio_path.exists() and best_segment is not None:
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
    transcript_segments: list[TranscriptSegment],
    diarization_segments: list[DiarizationSegment],
):
    return assign_speakers_by_overlap(transcript_segments, diarization_segments)


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


def _best_sample_segment(
    speaker: str,
    transcript_segments: list[TranscriptSegment],
    diarization_segments: list[DiarizationSegment],
):
    diarized = [segment for segment in diarization_segments if segment.speaker == speaker]
    if diarized:
        return max(diarized, key=lambda item: item.end - item.start)
    return max(transcript_segments, key=lambda item: item.end - item.start, default=None)


def _is_mic_speaker(speaker: str, config: AppConfig) -> bool:
    return speaker in {MIC_SPEAKER_LABEL, config.speakers.mic_speaker_name}
