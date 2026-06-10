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
    body = "\n".join(
        [
            "## Summary",
            "",
            linkify_entity_mentions(parsed.summary, catalog),
            "",
            "---",
            "",
            "## Key Points",
            "",
            _bullet_section(enrichment.key_points, catalog),
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
            _bullet_section(enrichment.decisions, catalog),
            "",
            "---",
            "",
            "## Action Items",
            "",
            _action_items_section(enrichment, catalog),
            "",
            "---",
            "",
            "## Open Questions",
            "",
            _bullet_section(enrichment.open_questions, catalog),
            "",
            "---",
            "",
            "## Links Mentioned",
            "",
            _bullet_section(enrichment.links_mentioned),
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
    return updated


def _replace_or_insert_block(content: str, key: str, lines: list[str]) -> str:
    pattern = rf"^{re.escape(key)}:\n(?:^(?:  - |\s{{4}}).*\n?)*"
    replacement = key + ":\n" + "\n".join(lines) + "\n"
    if re.search(pattern, content, flags=re.MULTILINE):
        return re.sub(pattern, replacement, content, flags=re.MULTILINE)
    if content.startswith("---\n"):
        return content.replace("---\n", "---\n" + replacement, 1)
    return replacement + content


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
            lines.append(f"- {item.owner}: {text}")
        else:
            lines.append(f"- {text}")
    return "\n".join(lines)
