from pathlib import Path

from mt_linux.config import AppConfig
from mt_linux.enrichment.service import enrich_note


def test_enrich_note_extracts_sections_links_tags_and_entities(tmp_path: Path):
    config = AppConfig()
    config.enrichment.entity_catalog_path = str(tmp_path / "entities.toml")
    Path(config.enrichment.entity_catalog_path).write_text(
        """
[projects."P10 Operations"]
aliases = ["p10 operations", "operations"]

[brands."Paratek / TYMLOS"]
aliases = ["tymlos"]
clients = ["Paratek"]

[clients."Abbott"]
aliases = ["abbott"]

[clients."Paratek"]
aliases = ["paratek"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    summary = """**Summary**

- Discussion of Abbott permissions in P10 Operations

**Decisions**

- Add Ava and Brenda to the top-level share

**Action Items**

- James Tomasino will update the onboarding doc
"""
    transcript = """
[[James Tomasino]]: Can Mike review the current access rules?
[[Syd Bizovi]]: See https://example.com/doc for the Tymlos share list.
"""
    enrichment = enrich_note(summary, transcript, config)
    assert "Discussion of Abbott permissions in P10 Operations" in enrichment.key_points
    assert "Add Ava and Brenda to the top-level share" in enrichment.decisions
    assert enrichment.action_items[0].owner == "James Tomasino"
    assert enrichment.links_mentioned == ["https://example.com/doc"]
    assert enrichment.related_projects == ["P10 Operations"]
    assert enrichment.related_brands == ["Paratek / TYMLOS"]
    assert enrichment.related_clients == ["Abbott", "Paratek"]
    assert "abbott" in enrichment.tags
