"""Tests for the enhanced enrichment pipeline."""

from pathlib import Path

from mt_linux.config import AppConfig
from mt_linux.enrichment.discovery import (
    check_spelling,
    apply_spell_corrections,
    _levenshtein_distance,
    _build_catalog_text,
)
from mt_linux.enrichment.entities import EntityCatalog
from mt_linux.enrichment.auto_entities import (
    create_entity_notes,
    _safe_filename,
    add_meeting_reference,
)
from mt_linux.enrichment.models import (
    DiscoveredEntity,
    SpellCorrection,
    MeetingTopic,
    MeetingQuality,
    NoteEnrichment,
    ActionItem,
)


# ---------------------------------------------------------------------------
# Levenshtein distance
# ---------------------------------------------------------------------------


def test_levenshtein_identical():
    assert _levenshtein_distance("abc", "abc") == 0


def test_levenshtein_empty():
    assert _levenshtein_distance("", "abc") == 3
    assert _levenshtein_distance("abc", "") == 3


def test_levenshtein_one_edit():
    assert _levenshtein_distance("tymlos", "timlos") == 1


def test_levenshtein_two_edits():
    assert _levenshtein_distance("paratek", "paratech") == 2


def test_levenshtein_multiple_edits():
    assert _levenshtein_distance("hello", "hallo") == 1
    assert _levenshtein_distance("kitten", "sitting") == 3


# ---------------------------------------------------------------------------
# Spell checking
# ---------------------------------------------------------------------------


def test_check_spelling_catches_misspellings(tmp_path: Path):
    config = AppConfig()
    config.enrichment.entity_catalog_path = str(tmp_path / "entities.toml")
    catalog_path = Path(config.enrichment.entity_catalog_path)
    catalog_path.write_text(
        """
[brands."TYMLOS"]
aliases = ["tymlos"]

[clients."Paratek"]
aliases = ["paratek"]
""",
        encoding="utf-8",
    )
    catalog = EntityCatalog.load(catalog_path)

    # Text with a misspelling of tymlos -> timlos (1 edit distance)
    text = "Discussion about timlos branding"
    corrections = check_spelling(text, catalog)

    # Should find "timlos" -> "TYMLOS"
    assert any(sc.original == "timlos" and sc.corrected == "TYMLOS" for sc in corrections)


def test_apply_spell_corrections_replaces_words():
    corrections = [
        SpellCorrection(original="timlos", corrected="TYMLOS", entity_type="brand", confidence=0.9),
        SpellCorrection(original="paratech", corrected="Paratek", entity_type="client", confidence=0.8),
    ]
    text = "We discussed timlos and paratech branding today."
    result = apply_spell_corrections(text, corrections)
    assert "TYMLOS" in result
    assert "Paratek" in result
    assert "timlos" not in result.lower() or "TYMLOS" in result


def test_apply_spell_corrections_skips_low_confidence():
    corrections = [
        SpellCorrection(original="foo", corrected="bar", entity_type="project", confidence=0.3),
    ]
    text = "This is a foo test."
    result = apply_spell_corrections(text, corrections)
    assert "foo" in result  # Not corrected due to low confidence


# ---------------------------------------------------------------------------
# Entity note creation
# ---------------------------------------------------------------------------


def test_safe_filename(tmp_path: Path):
    assert _safe_filename("John Doe") == "John Doe"
    assert _safe_filename("Project: Alpha & Beta") == "Project Alpha Beta"
    assert _safe_filename("  spaced  name  ") == "spaced name"


def test_create_entity_notes(tmp_path: Path):
    config = AppConfig()
    config.enrichment.entity_notes_root = str(tmp_path / "Entities")
    config.output.folder = str(tmp_path / "Meetings")

    entities = [
        DiscoveredEntity(
            name="New Product X",
            entity_type="product",
            confidence=0.9,
            context="Mentioned as a new product in development",
            relationships=["Paratek"],
        ),
        DiscoveredEntity(
            name="John Smith",
            entity_type="person",
            confidence=0.85,
            context="Referenced as a stakeholder",
        ),
        # Low confidence entity should be skipped
        DiscoveredEntity(
            name="Uncertain Entity",
            entity_type="concept",
            confidence=0.3,
            context="Might be something",
        ),
    ]

    created = create_entity_notes(entities, config)

    # Should create 2 notes (skip low confidence)
    assert len(created) == 2

    # Check product note exists
    product_note = tmp_path / "Entities" / "Products" / "New Product X.md"
    assert product_note.exists()
    content = product_note.read_text(encoding="utf-8")
    assert 'title: "New Product X"' in content
    assert 'entity_type: "product"' in content
    assert "Mentioned as a new product in development" in content
    assert "[[Paratek]]" in content

    # Check person note exists
    person_note = tmp_path / "Entities" / "People" / "John Smith.md"
    assert person_note.exists()
    content = person_note.read_text(encoding="utf-8")
    assert 'title: "John Smith"' in content
    assert 'entity_type: "person"' in content


def test_create_entity_notes_updates_existing(tmp_path: Path):
    config = AppConfig()
    config.enrichment.entity_notes_root = str(tmp_path / "Entities")
    config.output.folder = str(tmp_path / "Meetings")

    # Pre-create an entity note
    entities_root = tmp_path / "Entities" / "People"
    entities_root.mkdir(parents=True)
    existing_note = entities_root / "Jane Doe.md"
    existing_note.write_text(
        """---
title: "Jane Doe"
entity_type: "person"
aliases:
  - "jane doe"
---

# Jane Doe

## Context

Original context.
""",
        encoding="utf-8",
    )

    entities = [
        DiscoveredEntity(
            name="Jane Doe",
            entity_type="person",
            confidence=0.9,
            context="New context about Jane from a different meeting",
        ),
    ]

    created = create_entity_notes(entities, config)
    assert len(created) == 1

    content = existing_note.read_text(encoding="utf-8")
    assert "Original context" in content
    assert "New context about Jane from a different meeting" in content


def test_add_meeting_reference(tmp_path: Path):
    entity_path = tmp_path / "Entities" / "People" / "Test Person.md"
    entity_path.parent.mkdir(parents=True)
    entity_path.write_text(
        """---
title: "Test Person"
entity_type: "person"
---

# Test Person

## Meetings

_This section will be auto-populated as meetings reference this entity._
""",
        encoding="utf-8",
    )

    added = add_meeting_reference(entity_path, "Weekly Sync", "2026-06-26")
    assert added is True

    content = entity_path.read_text(encoding="utf-8")
    assert "**2026-06-26**: Weekly Sync" in content

    # Should not add duplicate
    added_again = add_meeting_reference(entity_path, "Weekly Sync", "2026-06-26")
    assert added_again is False


# ---------------------------------------------------------------------------
# Model serialization
# ---------------------------------------------------------------------------


def test_note_enrichment_roundtrip():
    original = NoteEnrichment(
        key_points=["Point 1", "Point 2"],
        decisions=["Decision A"],
        action_items=[ActionItem(text="Do thing", owner="Alice", due="2026-07-01")],
        open_questions=["What about X?"],
        links_mentioned=["https://example.com"],
        related_projects=["Project Alpha"],
        related_brands=["Brand Beta"],
        related_clients=["Client Gamma"],
        tags=["meeting", "project-alpha"],
        discovered_entities=[
            DiscoveredEntity(name="New Entity", entity_type="organization", confidence=0.9),
        ],
        spell_corrections=[
            SpellCorrection(original="misspelling", corrected="correction", entity_type="project", confidence=0.85),
        ],
        meeting_topics=[
            MeetingTopic(name="Strategy", weight=0.9, related_entities=["Project Alpha"]),
        ],
        meeting_quality=MeetingQuality(
            overall_score=0.85,
            audio_quality="good",
            gaps=["Gap at 15:00"],
            speaker_coverage=0.9,
            recommendations=["Use better mic"],
        ),
        sentiment="positive",
        key_people=["External Stakeholder"],
        deadlines_mentioned=["Q3 2026 launch"],
        documents_mentioned=["Strategy Deck v2"],
        related_meetings=["2026-06-25_meeting"],
    )

    data = original.to_dict()
    restored = NoteEnrichment.from_dict(data)

    assert restored.key_points == original.key_points
    assert restored.decisions == original.decisions
    assert restored.action_items[0].text == original.action_items[0].text
    assert restored.discovered_entities[0].name == "New Entity"
    assert restored.spell_corrections[0].original == "misspelling"
    assert restored.meeting_topics[0].name == "Strategy"
    assert restored.meeting_quality.overall_score == 0.85
    assert restored.sentiment == "positive"
    assert restored.key_people == original.key_people
    assert restored.deadlines_mentioned == original.deadlines_mentioned
    assert restored.documents_mentioned == original.documents_mentioned


def test_note_enrichment_default_values():
    e = NoteEnrichment()
    assert e.sentiment == "neutral"
    assert e.discovered_entities == []
    assert e.spell_corrections == []
    assert e.meeting_topics == []
    assert e.meeting_quality is None
    assert e.key_people == []
    assert e.deadlines_mentioned == []
    assert e.documents_mentioned == []


def test_build_catalog_text():
    catalog = EntityCatalog(
        projects={"Project A": type("R", (), {"aliases": ["Project A", "proj-a"]})()},
        brands={"Brand X": type("R", (), {"aliases": ["Brand X"]})()},
        clients={},
    )
    text = _build_catalog_text(catalog)
    assert "Project A" in text
    assert "Brand X" in text
    assert "proj-a" in text


def test_build_catalog_text_empty():
    catalog = EntityCatalog()
    text = _build_catalog_text(catalog)
    assert "empty catalog" in text.lower()


# ---------------------------------------------------------------------------
# Open questions section rendering
# ---------------------------------------------------------------------------


def test_open_questions_section_with_emoji():
    from mt_linux.output.enrichment_patch import _open_questions_section

    enrichment = NoteEnrichment(
        open_questions=["What is the timeline?", "Who owns this?"]
    )
    result = _open_questions_section(enrichment.open_questions)
    assert "❓" in result
    assert "What is the timeline?" in result
    assert "Who owns this?" in result


def test_open_questions_section_empty():
    from mt_linux.output.enrichment_patch import _open_questions_section

    result = _open_questions_section([])
    assert result == ""


# ---------------------------------------------------------------------------
# Topics section rendering
# ---------------------------------------------------------------------------


def test_topics_section_with_weights():
    from mt_linux.output.enrichment_patch import _topics_section
    from mt_linux.enrichment.entities import EntityCatalog

    enrichment = NoteEnrichment(
        meeting_topics=[
            MeetingTopic(name="Strategy", weight=0.9),
            MeetingTopic(name="Budget", weight=0.6),
            MeetingTopic(name="Misc", weight=0.3),
        ]
    )
    result = _topics_section(enrichment, EntityCatalog())
    assert "🔥" in result  # High weight
    assert "📌" in result  # Medium weight
    assert "📝" in result  # Low weight


# ---------------------------------------------------------------------------
# Quality section rendering
# ---------------------------------------------------------------------------


def test_quality_section_good():
    from mt_linux.output.enrichment_patch import _quality_section

    enrichment = NoteEnrichment(
        meeting_quality=MeetingQuality(
            overall_score=0.9,
            audio_quality="good",
            gaps=[],
            speaker_coverage=0.95,
            recommendations=["Keep doing what you're doing"],
        )
    )
    result = _quality_section(enrichment)
    assert "[!info]" in result
    assert "Good Quality" in result


def test_quality_section_poor():
    from mt_linux.output.enrichment_patch import _quality_section

    enrichment = NoteEnrichment(
        meeting_quality=MeetingQuality(
            overall_score=0.3,
            audio_quality="poor",
            gaps=["Long silence at 10:00", "Overlapping speech at 20:00"],
            speaker_coverage=0.4,
            recommendations=["Use headsets", "One person at a time"],
        )
    )
    result = _quality_section(enrichment)
    assert "[!bug]" in result
    assert "Low Quality" in result
    assert "Gaps detected" in result
    assert "Recommendations" in result


# ---------------------------------------------------------------------------
# Spell corrections section rendering
# ---------------------------------------------------------------------------


def test_spell_corrections_section():
    from mt_linux.output.enrichment_patch import _spell_corrections_section

    enrichment = NoteEnrichment(
        spell_corrections=[
            SpellCorrection(original="timlos", corrected="TYMLOS", entity_type="brand", confidence=0.9),
            SpellCorrection(original="paratech", corrected="Paratek", entity_type="client", confidence=0.7),
        ]
    )
    result = _spell_corrections_section(enrichment)
    assert "[!abstract]" in result
    assert "`timlos`" in result
    assert "**TYMLOS**" in result


def test_spell_corrections_section_empty():
    from mt_linux.output.enrichment_patch import _spell_corrections_section

    enrichment = NoteEnrichment()
    result = _spell_corrections_section(enrichment)
    assert result == ""


# ---------------------------------------------------------------------------
# Frontmatter scalar replacement
# ---------------------------------------------------------------------------


def test_replace_or_insert_scalar():
    from mt_linux.output.enrichment_patch import _replace_or_insert_scalar

    content = """---
title: "Old Title"
date: 2026-06-26
---"""

    updated = _replace_or_insert_scalar(content, "title", "New Title")
    assert 'title: New Title' in updated
    assert 'title: "Old Title"' not in updated

    # Insert new scalar
    updated = _replace_or_insert_scalar(content, "sentiment", "positive")
    assert "sentiment: positive" in updated


# ---------------------------------------------------------------------------
# Frontmatter block replacement
# ---------------------------------------------------------------------------


def test_replace_or_insert_block():
    from mt_linux.output.enrichment_patch import _replace_or_insert_block

    content = """---
tags:
  - "meeting"
  - "old-tag"
---"""

    updated = _replace_or_insert_block(content, "tags", ['  - "meeting"', '  - "new-tag"'])
    assert '  - "new-tag"' in updated
    assert '  - "old-tag"' not in updated


def test_replace_or_insert_block_new_key():
    from mt_linux.output.enrichment_patch import _replace_or_insert_block

    content = """---
title: "Test"
---"""

    updated = _replace_or_insert_block(content, "key_people", ['  - "Alice"'])
    assert 'key_people:' in updated
    assert '  - "Alice"' in updated
