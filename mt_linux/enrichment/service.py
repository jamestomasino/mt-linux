from __future__ import annotations

from pathlib import Path

from mt_linux.config import AppConfig
from mt_linux.enrichment.entities import EntityCatalog, apply_entity_matches
from mt_linux.enrichment.models import NoteEnrichment
from mt_linux.enrichment.protocol_sections import extract_protocol_enrichment
from mt_linux.enrichment.vault_entities import default_entity_notes_root, write_entity_catalog


def enrich_note(summary: str, transcript: str, config: AppConfig) -> NoteEnrichment:
    enrichment = extract_protocol_enrichment(summary, transcript)
    if not config.enrichment.enabled:
        return enrichment
    catalog = load_entity_catalog(config)
    return apply_entity_matches(enrichment, f"{summary}\n{transcript}", catalog)


def load_entity_catalog(config: AppConfig) -> EntityCatalog:
    sync_entity_catalog(config)
    return EntityCatalog.load(config.resolve_path(config.enrichment.entity_catalog_path))


def ensure_catalog_file(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[projects]\n\n[clients]\n",
        encoding="utf-8",
    )


def sync_entity_catalog(config: AppConfig) -> Path:
    target = config.resolve_path(config.enrichment.entity_catalog_path)
    notes_root = entity_notes_root(config)
    if notes_root.exists():
        write_entity_catalog(notes_root, target)
    elif not target.exists():
        ensure_catalog_file(target)
    return target


def entity_notes_root(config: AppConfig) -> Path:
    if config.enrichment.entity_notes_root:
        return config.resolve_path(config.enrichment.entity_notes_root)
    if config.output.vault_root:
        return config.resolve_path(config.output.vault_root) / "Entities"
    output_dir = config.resolve_path(config.output.folder)
    return default_entity_notes_root(output_dir)
