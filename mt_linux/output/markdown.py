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
    enrichment = enrichment or NoteEnrichment()
    frontmatter = _frontmatter(
        job,
        config,
        identities,
        enrichment=enrichment,
        transcription_confidence=transcription_confidence,
    )
    participants_table = _participants_table(identities)
    transcript_body = _transcript_body(job, transcript_segments, identities)
    summary_text = summary or "No protocol generated - transcript only."
    summary_text = linkify_entity_mentions(summary_text, catalog)

    # Build sections
    key_points = _bullet_section(enrichment.key_points, catalog)
    decisions = _bullet_section(enrichment.decisions, catalog)
    action_items = _action_items_section(enrichment, catalog)
    open_questions = _open_questions_section(enrichment.open_questions)
    links_mentioned = _bullet_section(enrichment.links_mentioned)
    topics_section = _topics_section(enrichment, catalog)
    people_section = _key_people_section(enrichment, catalog)
    deadlines_section = _deadlines_section(enrichment)
    documents_section = _documents_section(enrichment, catalog)
    quality_section = _quality_section(enrichment)
    spell_section = _spell_corrections_section(enrichment)
    daily_note_link = _daily_note_link(job.meeting_info.start_time)
    related_meetings_section = _related_meetings_section(enrichment)

    content = "\n".join(
        [
            frontmatter,
            daily_note_link,
            "## Summary",
            "",
            summary_text.strip(),
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
            "## Topics",
            "",
            topics_section,
            "",
            "---",
            "",
            "## Key People Mentioned",
            "",
            people_section,
            "",
            "---",
            "",
            "## Deadlines",
            "",
            deadlines_section,
            "",
            "---",
            "",
            "## Documents Mentioned",
            "",
            documents_section,
            "",
            "---",
            "",
            "## Related Meetings",
            "",
            related_meetings_section,
            "",
            "---",
            "",
            "## Meeting Quality",
            "",
            quality_section,
            "",
            "---",
            "",
            "## Spell Corrections",
            "",
            spell_section,
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


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------


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
        f"sentiment: {enrichment.sentiment}",
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

    # Related entities
    lines.append("related_projects:")
    lines.extend([f'  - "{value}"' for value in enrichment.related_projects] or ['  - ""'])
    lines.append("related_brands:")
    lines.extend([f'  - "{value}"' for value in enrichment.related_brands] or ['  - ""'])
    lines.append("related_clients:")
    lines.extend([f'  - "{value}"' for value in enrichment.related_clients] or ['  - ""'])

    # New: key people
    lines.append("key_people:")
    lines.extend([f'  - "{value}"' for value in enrichment.key_people] or ['  - ""'])

    # New: deadlines
    lines.append("deadlines_mentioned:")
    lines.extend([f'  - "{value}"' for value in enrichment.deadlines_mentioned] or ['  - ""'])

    # New: documents
    lines.append("documents_mentioned:")
    lines.extend([f'  - "{value}"' for value in enrichment.documents_mentioned] or ['  - ""'])

    # New: topics
    lines.append("meeting_topics:")
    lines.extend([f'  - "{value}"' for value in [t.name for t in enrichment.meeting_topics]] or ['  - ""'])

    # Links
    lines.append("links_mentioned:")
    lines.extend([f'  - "{value}"' for value in enrichment.links_mentioned] or ['  - ""'])

    # Action items
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

    # Spell corrections
    lines.append("spell_corrections:")
    if enrichment.spell_corrections:
        for sc in enrichment.spell_corrections:
            lines.append(f'  - original: "{sc.original}"')
            lines.append(f'    corrected: "{sc.corrected}"')
            lines.append(f'    confidence: {sc.confidence}')
    else:
        lines.append('  - original: ""')
        lines.append('    corrected: ""')
        lines.append('    confidence: 0')

    # Meeting quality
    if enrichment.meeting_quality:
        mq = enrichment.meeting_quality
        lines.append(f"meeting_quality_score: {mq.overall_score}")
        lines.append(f"meeting_quality_audio: {mq.audio_quality}")
        lines.append(f"meeting_quality_speaker_coverage: {mq.speaker_coverage}")
        lines.append("meeting_quality_gaps:")
        lines.extend([f'  - "{g}"' for g in mq.gaps] or ['  - ""'])
        lines.append("meeting_quality_recommendations:")
        lines.extend([f'  - "{r}"' for r in mq.recommendations] or ['  - ""'])

    # Calendar attendees
    lines.append("calendar_attendees:")
    lines.extend(attendees or ['  - ""'])

    # Calendar candidates
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


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


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
    clamped = max(-3.0, min(0.0, avg))
    return round((clamped + 3.0) / 3.0 * 100, 1)


def _topics_section(enrichment: NoteEnrichment, catalog: EntityCatalog) -> str:
    if not enrichment.meeting_topics:
        return ""
    lines: list[str] = []
    for topic in enrichment.meeting_topics:
        name = linkify_entity_mentions(topic.name, catalog)
        weight_emoji = "🔥" if topic.weight >= 0.8 else "📌" if topic.weight >= 0.5 else "📝"
        lines.append(f"- {weight_emoji} {name}")
        if topic.related_entities:
            for entity in topic.related_entities:
                lines.append(f"  - [[{entity}]]")
    return "\n".join(lines)


def _key_people_section(enrichment: NoteEnrichment, catalog: EntityCatalog) -> str:
    if not enrichment.key_people:
        return ""
    lines: list[str] = []
    for person in enrichment.key_people:
        lines.append(f"- [[{person}]]")
    return "\n".join(lines)


def _deadlines_section(enrichment: NoteEnrichment) -> str:
    if not enrichment.deadlines_mentioned:
        return ""
    lines: list[str] = []
    for deadline in enrichment.deadlines_mentioned:
        lines.append(f"- ⏰ {deadline}")
    return "\n".join(lines)


def _documents_section(enrichment: NoteEnrichment, catalog: EntityCatalog) -> str:
    if not enrichment.documents_mentioned:
        return ""
    lines: list[str] = []
    for doc in enrichment.documents_mentioned:
        linked = linkify_entity_mentions(doc, catalog)
        lines.append(f"- 📄 {linked}")
    return "\n".join(lines)


def _open_questions_section(questions: list[str]) -> str:
    if not questions:
        return ""
    lines: list[str] = []
    for q in questions:
        lines.append(f"- ❓ {q}")
    return "\n".join(lines)


def _related_meetings_section(enrichment: NoteEnrichment) -> str:
    if not enrichment.related_meetings:
        return ""
    lines: list[str] = []
    for meeting in enrichment.related_meetings:
        lines.append(f"- [[{meeting}]]")
    return "\n".join(lines)


def _quality_section(enrichment: NoteEnrichment) -> str:
    if not enrichment.meeting_quality:
        return ""
    mq = enrichment.meeting_quality
    lines: list[str] = []

    # Obsidian callout for quality
    score = mq.overall_score
    if score >= 0.8:
        callout_type = "info"
        callout_title = "✅ Good Quality"
    elif score >= 0.5:
        callout_type = "warning"
        callout_title = "⚠️ Moderate Quality"
    else:
        callout_type = "bug"
        callout_title = "❌ Low Quality"

    lines.append(f"> [!{callout_type}] {callout_title} (score: {score:.0%})")
    lines.append(f"> Audio quality: {mq.audio_quality} | Speaker coverage: {mq.speaker_coverage:.0%}")

    if mq.gaps:
        lines.append(">")
        lines.append("> **Gaps detected:**")
        for gap in mq.gaps:
            lines.append(f"> - {gap}")

    if mq.recommendations:
        lines.append(">")
        lines.append("> **Recommendations:**")
        for rec in mq.recommendations:
            lines.append(f"> - {rec}")

    return "\n".join(lines)


def _spell_corrections_section(enrichment: NoteEnrichment) -> str:
    if not enrichment.spell_corrections:
        return ""
    lines: list[str] = []
    lines.append("> [!abstract] Spell Corrections Detected")
    for sc in enrichment.spell_corrections:
        if sc.confidence >= 0.5:
            lines.append(f"> - `{sc.original}` → **{sc.corrected}** ({sc.entity_type}, confidence: {sc.confidence:.0%})")
    return "\n".join(lines)


def _daily_note_link(start_time) -> str:
    """Create a link to the Obsidian daily note for this date."""
    date_str = start_time.strftime("%Y-%m-%d")
    return f"\n[[{date_str}]]\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
            lines.append(f"- ✅ **{item.owner}**: {text}")
        else:
            lines.append(f"- ✅ {text}")
        if item.due:
            lines.append(f"  - Due: {item.due}")
        if item.status:
            lines.append(f"  - Status: {item.status}")
    return "\n".join(lines)


def _wikify(name: str) -> str:
    return f"[[{name}]]" if name and not name.startswith("[[") else name


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
