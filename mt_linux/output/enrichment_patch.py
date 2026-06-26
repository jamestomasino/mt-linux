from __future__ import annotations

from pathlib import Path
import re

from mt_linux.config import AppConfig
from mt_linux.enrichment.entities import EntityCatalog, linkify_entity_mentions
from mt_linux.enrichment.models import NoteEnrichment
from mt_linux.enrichment.service import load_entity_catalog
from mt_linux.output.note_content import parse_note_content


def apply_note_enrichment(path: Path, enrichment: NoteEnrichment, config: AppConfig | None = None) -> None:
    content = path.read_text(encoding="utf-8")
    parsed = parse_note_content(content)
    catalog = load_entity_catalog(config) if config and config.enrichment.enabled else EntityCatalog()
    frontmatter = _update_frontmatter(parsed.frontmatter, enrichment)

    summary_text = linkify_entity_mentions(parsed.summary, catalog)
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

    body = "\n".join(
        [
            "## Summary",
            "",
            summary_text,
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
            parsed.participants,
            "",
            "---",
            "",
            "## Decisions",
            "",
            decisions,
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
            parsed.transcript,
            "",
        ]
    )
    path.write_text(frontmatter + body, encoding="utf-8")


def _update_frontmatter(frontmatter: str, enrichment: NoteEnrichment) -> str:
    if not frontmatter:
        return ""
    updated = frontmatter
    updated = _replace_or_insert_block(updated, "related_projects", [f'  - "{item}"' for item in enrichment.related_projects] or ['  - ""'])
    updated = _replace_or_insert_block(updated, "related_brands", [f'  - "{item}"' for item in enrichment.related_brands] or ['  - ""'])
    updated = _replace_or_insert_block(updated, "related_clients", [f'  - "{item}"' for item in enrichment.related_clients] or ['  - ""'])
    updated = _replace_or_insert_block(updated, "links_mentioned", [f'  - "{item}"' for item in enrichment.links_mentioned] or ['  - ""'])
    updated = _replace_or_insert_block(updated, "tags", [f'  - "{item}"' for item in enrichment.tags] or ['  - ""'])
    updated = _replace_or_insert_block(updated, "key_people", [f'  - "{item}"' for item in enrichment.key_people] or ['  - ""'])
    updated = _replace_or_insert_block(updated, "deadlines_mentioned", [f'  - "{item}"' for item in enrichment.deadlines_mentioned] or ['  - ""'])
    updated = _replace_or_insert_block(updated, "documents_mentioned", [f'  - "{item}"' for item in enrichment.documents_mentioned] or ['  - ""'])
    updated = _replace_or_insert_block(updated, "meeting_topics", [f'  - "{t.name}"' for t in enrichment.meeting_topics] or ['  - ""'])

    # Sentiment
    updated = _replace_or_insert_scalar(updated, "sentiment", enrichment.sentiment)

    action_lines = []
    for item in enrichment.action_items:
        action_lines.extend(
            [
                f'  - owner: "{item.owner}"',
                f'    text: "{item.text}"',
                f'    status: "{item.status}"',
                f'    due: "{item.due}"',
            ]
        )
    updated = _replace_or_insert_block(updated, "action_items_structured", action_lines or ['  - owner: ""', '    text: ""', '    status: ""', '    due: ""'])

    # Spell corrections
    spell_lines = []
    if enrichment.spell_corrections:
        for sc in enrichment.spell_corrections:
            spell_lines.extend([
                f'  - original: "{sc.original}"',
                f'    corrected: "{sc.corrected}"',
                f'    confidence: {sc.confidence}',
            ])
    updated = _replace_or_insert_block(updated, "spell_corrections", spell_lines or ['  - original: ""', '    corrected: ""', '    confidence: 0'])

    return updated


def _replace_or_insert_block(content: str, key: str, lines: list[str]) -> str:
    pattern = rf"^{re.escape(key)}:\n(?:^(?:  - |\s{{4}}).*\n?)*"
    replacement = key + ":\n" + "\n".join(lines) + "\n"
    if re.search(pattern, content, flags=re.MULTILINE):
        return re.sub(pattern, replacement, content, flags=re.MULTILINE)
    if content.startswith("---\n"):
        return content.replace("---\n", "---\n" + replacement, 1)
    return replacement + content


def _replace_or_insert_scalar(content: str, key: str, value: str) -> str:
    pattern = rf"^{re.escape(key)}:.*$"
    replacement = f"{key}: {value}"
    if re.search(pattern, content, flags=re.MULTILINE):
        return re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)
    if content.startswith("---\n"):
        return content.replace("---\n", "---\n" + replacement + "\n", 1)
    return content + "\n" + replacement


def _bullet_section(items: list[str], catalog: EntityCatalog | None = None) -> str:
    if not items:
        return ""
    catalog = catalog or EntityCatalog()
    return "\n".join(f"- {linkify_entity_mentions(item, catalog)}" for item in items)


def _action_items_section(enrichment: NoteEnrichment, catalog: EntityCatalog | None = None) -> str:
    lines: list[str] = []
    catalog = catalog or EntityCatalog()
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


def _open_questions_section(questions: list[str]) -> str:
    if not questions:
        return ""
    lines: list[str] = []
    for q in questions:
        lines.append(f"- ❓ {q}")
    return "\n".join(lines)


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
    return "\n".join(f"- [[{person}]]" for person in enrichment.key_people)


def _deadlines_section(enrichment: NoteEnrichment) -> str:
    if not enrichment.deadlines_mentioned:
        return ""
    return "\n".join(f"- ⏰ {deadline}" for deadline in enrichment.deadlines_mentioned)


def _documents_section(enrichment: NoteEnrichment, catalog: EntityCatalog) -> str:
    if not enrichment.documents_mentioned:
        return ""
    lines: list[str] = []
    for doc in enrichment.documents_mentioned:
        linked = linkify_entity_mentions(doc, catalog)
        lines.append(f"- 📄 {linked}")
    return "\n".join(lines)


def _quality_section(enrichment: NoteEnrichment) -> str:
    if not enrichment.meeting_quality:
        return ""
    mq = enrichment.meeting_quality
    lines: list[str] = []
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
