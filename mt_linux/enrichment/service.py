from __future__ import annotations

from pathlib import Path

from mt_linux.config import AppConfig
from mt_linux.enrichment.auto_entities import create_entity_notes
from mt_linux.enrichment.discovery import enrich_with_llm, check_spelling
from mt_linux.enrichment.entities import EntityCatalog, apply_entity_matches
from mt_linux.enrichment.models import NoteEnrichment
from mt_linux.enrichment.protocol_sections import extract_protocol_enrichment
from mt_linux.enrichment.vault_entities import default_entity_notes_root, write_entity_catalog


def enrich_note(
    summary: str,
    transcript: str,
    config: AppConfig,
    run_discovery: bool = True,
) -> NoteEnrichment:
    """Full enrichment pipeline for a meeting note.

    Steps:
    1. Extract protocol sections (summary, decisions, action items) via regex.
    2. Match known entities from the catalog.
    3. Run local spell checking against the catalog.
    4. Optionally run LLM-powered discovery (new entities, topics, quality).
    5. Optionally create entity notes for high-confidence discoveries.
    """
    # Step 1: Extract structured sections from protocol
    enrichment = extract_protocol_enrichment(summary, transcript, config)

    if not config.enrichment.enabled:
        return enrichment

    # Step 2: Load catalog and match known entities
    catalog = load_entity_catalog(config)
    enrichment = apply_entity_matches(enrichment, f"{summary}\n{transcript}", catalog)

    # Step 3: Local spell checking (no LLM required)
    local_corrections = check_spelling(f"{summary}\n{transcript}", catalog)
    enrichment.spell_corrections.extend(local_corrections)

    # Step 4: LLM-powered discovery
    if run_discovery:
        enrichment = enrich_with_llm(summary, transcript, config, catalog, enrichment)

        # Step 5: Create entity notes for high-confidence discoveries
        if enrichment.discovered_entities:
            create_entity_notes(enrichment.discovered_entities, config)

    return enrichment


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
