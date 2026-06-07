from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
import re

from mt_linux.config import AppConfig
from mt_linux.models import SpeakerIdentity, TranscriptSegment
from mt_linux.pipeline.job import PipelineJob


@dataclass
class RenderedMeeting:
    path: Path
    content: str


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or "meeting"


def output_path_for(job: PipelineJob, config: AppConfig) -> Path:
    title = job.meeting_info.title or job.meeting_info.app
    start = job.meeting_info.start_time
    filename = f"{start:%Y-%m-%d}_{start:%H-%M}_{slugify(title)}.md"
    return config.resolve_path(config.output.folder) / filename


def render_meeting_markdown(
    job: PipelineJob,
    config: AppConfig,
    transcript_segments: list[TranscriptSegment],
    identities: list[SpeakerIdentity],
    summary: str = "",
    decisions: str = "",
    action_items: str = "",
    transcription_confidence: float | None = None,
) -> RenderedMeeting:
    output_path = output_path_for(job, config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = _frontmatter(
        job, config, identities, transcription_confidence=transcription_confidence
    )
    participants_table = _participants_table(identities)
    transcript_body = _transcript_body(job, transcript_segments, identities)
    summary = summary or "No protocol generated - transcript only."
    content = "\n".join(
        [
            frontmatter,
            "## Summary",
            "",
            summary.strip(),
            "",
            "---",
            "",
            "## Participants",
            "",
            participants_table,
            "",
            "---",
            "",
            "## Decisions",
            "",
            decisions.strip(),
            "",
            "---",
            "",
            "## Action Items",
            "",
            action_items.strip(),
            "",
            "---",
            "",
            "## Transcript",
            "",
            transcript_body,
            "",
        ]
    )
    return RenderedMeeting(path=output_path, content=content)


def _frontmatter(
    job: PipelineJob,
    config: AppConfig,
    identities: list[SpeakerIdentity],
    transcription_confidence: float | None = None,
) -> str:
    info = job.meeting_info
    event = info.calendar_event
    title = info.title or info.app
    participants = [f'  - "{_wikify(identity.name)}"' for identity in identities]
    attendees = []
    if event:
        attendees = [f'  - "{attendee.display()}"' for attendee in event.attendees]
    candidate_event_ids = [f'  - "{candidate.event_id}"' for candidate in info.calendar_candidates] or ['  - ""']
    audio_files = [job.app_audio_path, job.mic_audio_path]
    audio_entries = [f'  - "{path}"' for path in _relative_audio_paths(audio_files, config)]
    duration_minutes = 0
    if event:
        duration_minutes = int((event.end_time - event.start_time).total_seconds() // 60)
    lines = [
        "---",
        f'title: "{title}"',
        f"date: {info.start_time:%Y-%m-%d}",
        f'time: "{info.start_time:%H:%M}"',
        f"duration_minutes: {duration_minutes}",
        f"app: {info.app}",
        "participants:",
        *participants,
        f'organizer: "{_wikify(event.organizer) if event and event.organizer else ""}"',
        f'calendar_event_id: "{event.event_id if event else ""}"',
        f'calendar_match_confidence: "{info.calendar_match_confidence}"',
        f"calendar_review_queued: {'true' if info.calendar_review_queued else 'false'}",
        "calendar_candidate_event_ids:",
        *candidate_event_ids,
        "tags:",
        '  - "meeting"',
        '  - "transcript"',
        "status: complete",
        f'transcription_engine: "{config.transcription.engine}/{config.transcription.model}"',
        f'diarization: "{config.diarization.backend if config.diarization.enabled else "disabled"}"',
        "audio_files:",
        *audio_entries,
        f"transcription_confidence: {transcription_confidence if transcription_confidence is not None else 0.0}",
        "participants_identified:",
    ]
    for identity in identities:
        lines.append(f'  - name: "{_wikify(identity.name) if identity.name != identity.label else identity.name}"')
        lines.append(f'    confidence: "{identity.confidence}"')
        if identity.similarity is not None:
            lines.append(f"    similarity: {identity.similarity}")
        if identity.review_queued:
            lines.append("    review_queued: true")
    lines.append("calendar_attendees:")
    lines.extend(attendees or ['  - ""'])
    lines.append("calendar_candidates:")
    if info.calendar_candidates:
        for candidate in info.calendar_candidates:
            lines.append(f'  - id: "{candidate.event_id}"')
            lines.append(f'    title: "{candidate.title}"')
            lines.append(f'    conferencing: "{candidate.conferencing_type}"')
            lines.append(f'    response_status: "{candidate.response_status}"')
    else:
        lines.append('  - id: ""')
    lines.append("---")
    return "\n".join(lines)


def _participants_table(identities: list[SpeakerIdentity]) -> str:
    lines = [
        "| Speaker | Identity | Confidence |",
        "|---------|----------|------------|",
    ]
    for identity in identities:
        display = _wikify(identity.name) if identity.name != identity.label else identity.name
        lines.append(f"| {identity.label} | {display} | {identity.confidence} |")
    return "\n".join(lines)


def _transcript_body(
    job: PipelineJob, segments: list[TranscriptSegment], identities: list[SpeakerIdentity]
) -> str:
    identity_map = {identity.label: identity for identity in identities}
    lines: list[str] = []
    for segment in segments:
        timestamp = job.meeting_info.start_time + timedelta(seconds=segment.start)
        identity = identity_map.get(segment.speaker)
        name = identity.name if identity else segment.speaker
        speaker = _wikify(name) if identity and name != segment.speaker else name
        lines.append(f"**{timestamp:%H:%M:%S}** {speaker}: {segment.text.strip()}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _relative_audio_paths(paths: list[Path], config: AppConfig) -> list[str]:
    vault_root = config.resolve_path(config.output.vault_root) if config.output.vault_root else None
    result: list[str] = []
    for path in paths:
        if vault_root:
            try:
                result.append(str(path.resolve().relative_to(vault_root.resolve())))
                continue
            except Exception:
                pass
        result.append(str(path))
    return result


def _wikify(name: str) -> str:
    return f"[[{name}]]" if name and not name.startswith("[[") else name
