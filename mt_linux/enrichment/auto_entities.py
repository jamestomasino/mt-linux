"""Auto-create entity notes in the Obsidian vault for discovered entities."""

from __future__ import annotations

import logging
from pathlib import Path

from mt_linux.config import AppConfig
from mt_linux.enrichment.models import DiscoveredEntity

logger = logging.getLogger(__name__)

# Entity type -> folder name mapping
_ENTITY_TYPE_FOLDER: dict[str, str] = {
    "person": "People",
    "organization": "Organizations",
    "location": "Locations",
    "product": "Products",
    "document": "Documents",
    "deadline": "Deadlines",
    "concept": "Concepts",
    "client": "Clients",
    "project": "Projects",
    "brand": "Brands",
}


def create_entity_notes(
    entities: list[DiscoveredEntity],
    config: AppConfig,
    min_confidence: float = 0.7,
) -> list[Path]:
    """Create Obsidian notes for discovered entities.

    Returns the list of paths that were created or updated.
    """
    created: list[Path] = []

    # Determine the Entities root
    entities_root = _get_entities_root(config)
    if not entities_root:
        return created

    for entity in entities:
        if entity.confidence < min_confidence:
            continue

        folder_name = _ENTITY_TYPE_FOLDER.get(entity.entity_type, "Concepts")
        entity_folder = entities_root / folder_name
        entity_folder.mkdir(parents=True, exist_ok=True)

        # Build file name from entity name
        filename = _safe_filename(entity.name)
        entity_path = entity_folder / f"{filename}.md"

        if entity_path.exists():
            # Update existing note with new context
            _update_entity_note(entity_path, entity)
        else:
            _create_entity_note(entity_path, entity, folder_name)

        created.append(entity_path)
        logger.info("Created/updated entity note: %s", entity_path)

    return created


def _get_entities_root(config: AppConfig) -> Path | None:
    """Get the entities root directory."""
    if config.enrichment.entity_notes_root:
        return config.resolve_path(config.enrichment.entity_notes_root)
    if config.output.vault_root:
        return config.resolve_path(config.output.vault_root) / "Entities"
    output_dir = config.resolve_path(config.output.folder)
    return output_dir.parent / "Entities"


def _safe_filename(name: str) -> str:
    """Convert entity name to a safe filename."""
    import re
    # Remove non-alphanumeric chars except spaces and hyphens
    cleaned = re.sub(r"[^a-zA-Z0-9\s\-]", "", name)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "Unknown"


def _create_entity_note(path: Path, entity: DiscoveredEntity, folder_name: str) -> None:
    """Create a new entity note with proper frontmatter."""
    entity_type_map = {
        "People": "person",
        "Organizations": "organization",
        "Locations": "location",
        "Products": "product",
        "Documents": "document",
        "Deadlines": "deadline",
        "Concepts": "concept",
        "Clients": "client",
        "Projects": "project",
        "Brands": "brand",
    }
    mapped_type = entity_type_map.get(folder_name, entity.entity_type)

    content = f"""---
title: "{entity.name}"
entity_type: "{mapped_type}"
aliases:
  - "{entity.name.lower()}"
discovery_confidence: {entity.confidence:.2f}
---

# {entity.name}

## Type

{entity.entity_type.title()}

## Context

{entity.context}
"""

    if entity.relationships:
        content += "\n## Related Entities\n\n"
        for rel in entity.relationships:
            content += f"- [[{rel}]]\n"

    content += "\n## Meetings\n\n"
    content += "_This section will be auto-populated as meetings reference this entity._\n"

    path.write_text(content, encoding="utf-8")


def _update_entity_note(path: Path, entity: DiscoveredEntity) -> None:
    """Update an existing entity note with new context if not already present."""
    content = path.read_text(encoding="utf-8")
    if entity.context and entity.context not in content:
        # Append new context
        if "## Context" in content:
            content = content.replace(
                "## Context\n\n",
                f"## Context\n\n{entity.context}\n",
                1,
            )
        else:
            content += f"\n## Context\n\n{entity.context}\n"
        path.write_text(content, encoding="utf-8")


def add_meeting_reference(entity_path: Path, meeting_title: str, meeting_date: str) -> bool:
    """Add a meeting reference to an entity note.

    Returns True if the reference was added, False if it already existed.
    """
    if not entity_path.exists():
        return False

    content = entity_path.read_text(encoding="utf-8")
    ref_line = f"- **{meeting_date}**: {meeting_title}"

    if ref_line in content:
        return False

    if "## Meetings" in content:
        content = content.replace(
            "## Meetings\n\n",
            f"## Meetings\n\n{ref_line}\n",
            1,
        )
    else:
        content += f"\n## Meetings\n\n{ref_line}\n"

    entity_path.write_text(content, encoding="utf-8")
    return True
