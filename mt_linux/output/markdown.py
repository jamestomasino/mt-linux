from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import re

from mt_linux.config import AppConfig
from mt_linux.enrichment.entities import EntityCatalog, linkify_entity_mentions
from mt_linux.enrichment.service import load_entity_catalog
from mt_linux.enrichment.models import NoteEnrichment
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
    enrichment: NoteEnrichment | None = None,
    transcription_confidence: float | None = None,
) -> RenderedMeeting:
    output_path = output_path_for(job, config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    catalog = load_entity_catalog(config) if config.enrichment.enabled else EntityCatalog()
    frontmatter = _frontmatter(
        job,
        config,
        identities,
        enrichment=enrichment,
        transcription_confidence=transcription_confidence,
    )
    participants_table = _participants_table(identities)
    transcript_body = _transcript_body(job, transcript_segments, identities)
    summary = summary or "No protocol generated - transcript only."
    summary = linkify_entity_mentions(summary, catalog)
    key_points = _bullet_section(enrichment.key_points if enrichment else [], catalog)
    decisions = _bullet_section(enrichment.decisions if enrichment else [], catalog)
    action_items = _action_items_section(enrichment, catalog)
    open_questions = _bullet_section(enrichment.open_questions if enrichment else [], catalog)
    links_mentioned = _bullet_section(enrichment.links_mentioned if enrichment else [])
    content = "\n".join(
        [
            frontmatter,
            "## Summary",
            "",
            summary.strip(),
            "",
            "---",
            "",
            "## Key Points",
            "",
            key_points,
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
            action_items,
            "",
            "---",
            "",
            "## Open Questions",
            "",
            open_questions,
            "",
            "---",
            "",
            "## Links Mentioned",
            "",
            links_mentioned,
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
    enrichment: NoteEnrichment | None = None,
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
    enrichment = enrichment or NoteEnrichment()
    tags = sorted({"meeting", "transcript", *enrichment.tags})
    lines = [
        "---",
        f'session_id: "{job.session_id}"',
        f'title: "{title}"',
        f"date: {info.start_time:%Y-%m-%d}",
        f'time: "{info.start_time:%H:%M}"',
        f"duration_minutes: {duration_minutes}",
        f"app: {info.app}",
        f'generated_at: "{datetime.now(UTC).isoformat()}"',
        "participants:",
        *participants,
        f'organizer: "{_wikify(event.organizer) if event and event.organizer else ""}"',
        f'calendar_event_id: "{event.event_id if event else ""}"',
        f'calendar_match_confidence: "{info.calendar_match_confidence}"',
        f"calendar_review_queued: {'true' if info.calendar_review_queued else 'false'}",
        f"meeting_review_complete: {'false' if info.calendar_review_queued else 'true'}",
        "calendar_candidate_event_ids:",
        *candidate_event_ids,
        "tags:",
        *[f'  - "{tag}"' for tag in tags],
        "status: complete",
        f'transcription_engine: "{config.transcription.engine}/{config.transcription.model}"',
        f'diarization: "{config.diarization.backend if config.diarization.enabled else "disabled"}"',
        "audio_files:",
        *audio_entries,
        f"transcription_confidence: {transcription_confidence if transcription_confidence is not None else 0.0}",
        f"speaker_review_complete: {'false' if any(identity.review_queued for identity in identities) else 'true'}",
        "participants_identified:",
    ]
    for identity in identities:
        lines.append(f'  - name: "{_wikify(identity.name) if identity.name != identity.label else identity.name}"')
        lines.append(f'    confidence: "{identity.confidence}"')
        if identity.similarity is not None:
            lines.append(f"    similarity: {identity.similarity}")
        if identity.review_queued:
            lines.append("    review_queued: true")
    lines.append("related_projects:")
    lines.extend([f'  - "{value}"' for value in enrichment.related_projects] or ['  - ""'])
    lines.append("related_brands:")
    lines.extend([f'  - "{value}"' for value in enrichment.related_brands] or ['  - ""'])
    lines.append("related_clients:")
    lines.extend([f'  - "{value}"' for value in enrichment.related_clients] or ['  - ""'])
    lines.append("links_mentioned:")
    lines.extend([f'  - "{value}"' for value in enrichment.links_mentioned] or ['  - ""'])
    lines.append("action_items_structured:")
    if enrichment.action_items:
        for item in enrichment.action_items:
            lines.append(f'  - owner: "{item.owner}"')
            lines.append(f'    text: "{item.text}"')
            lines.append(f'    status: "{item.status}"')
            lines.append(f'    due: "{item.due}"')
    else:
        lines.append('  - owner: ""')
        lines.append('    text: ""')
        lines.append('    status: ""')
        lines.append('    due: ""')
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
    identity_map.update({identity.name: identity for identity in identities if identity.name})
    lines: list[str] = []
    for turn in _merge_speaker_turns(segments):
        timestamp = job.meeting_info.start_time + timedelta(seconds=turn.start)
        identity = identity_map.get(turn.speaker)
        name = identity.name if identity else turn.speaker
        speaker = _wikify(name) if identity and name != turn.speaker else name
        lines.append(f"**{timestamp:%H:%M:%S}** {speaker}: {turn.text.strip()}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _merge_speaker_turns(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Merge consecutive same-speaker segments, but break on gaps > 10 seconds."""
    MAX_GAP = 10.0
    turns: list[TranscriptSegment] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        if (
            turns
            and turns[-1].speaker == segment.speaker
            and (segment.start - turns[-1].end) <= MAX_GAP
        ):
            turns[-1].end = segment.end
            turns[-1].text = f"{turns[-1].text} {text}".strip()
            continue
        turns.append(
            TranscriptSegment(
                start=segment.start,
                end=segment.end,
                text=text,
                speaker=segment.speaker,
                confidence=segment.confidence,
            )
        )
    return turns


def _compute_transcription_confidence(
    segments: list[TranscriptSegment],
) -> float:
    """Average logprob-based confidence across all transcript segments.

    Whisper avg_logprob ranges from -inf (very uncertain) to 0 (certain).
    Values above -0.5 are excellent, below -1.0 are poor.
    We map to 0-100 for readability in frontmatter.
    """
    confidences = [
        s.confidence
        for s in segments
        if s.confidence is not None and s.text.strip()
    ]
    if not confidences:
        return 0.0
    avg = sum(confidences) / len(confidences)
    # Sigmoid-ish mapping: -2.0 -> ~12%, -1.0 -> ~27%, -0.5 -> ~38%, 0 -> 50%
    # But Whisper logprobs are typically -0.3 to -2.0 for decent transcripts.
    # Clamp and scale to a more useful 0-100 range.
    clamped = max(-3.0, min(0.0, avg))
    return round((clamped + 3.0) / 3.0 * 100, 1)


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


def _bullet_section(items: list[str], catalog: EntityCatalog | None = None) -> str:
    if not items:
        return ""
    catalog = catalog or EntityCatalog()
    return "\n".join(f"- {linkify_entity_mentions(item, catalog)}" for item in items)


def _action_items_section(enrichment: NoteEnrichment | None, catalog: EntityCatalog | None = None) -> str:
    if enrichment is None or not enrichment.action_items:
        return ""
    catalog = catalog or EntityCatalog()
    lines: list[str] = []
    for item in enrichment.action_items:
        text = linkify_entity_mentions(item.text, catalog)
        if item.owner:
            lines.append(f"- {item.owner}: {text}")
        else:
            lines.append(f"- {text}")
    return "\n".join(lines)
