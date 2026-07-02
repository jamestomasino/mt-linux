from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from mt_linux.cli import cli
from mt_linux.config import AppConfig
from mt_linux.output.enrichment_patch import is_already_enriched, get_enriched_at, get_enriched_at_from_frontmatter


_BASE_NOTE = """\
---
title: "Test Meeting"
tags:
  - "meeting"
  - "transcript"
---
## Summary

Test summary.

---

## Participants

| Speaker | Identity | Confidence |
|---------|----------|------------|
| [[Alice]] | [[Alice]] | voice_profile |

---

## Transcript

**10:00:00** [[Alice]]: Hello world.
"""


_ENRICHED_NOTE = """\
---
title: "Test Meeting"
enriched_at: "2026-06-15T12:00:00+00:00"
tags:
  - "meeting"
  - "transcript"
---
## Summary

Test summary.

---

## Participants

| Speaker | Identity | Confidence |
|---------|----------|------------|
| [[Alice]] | [[Alice]] | voice_profile |

---

## Transcript

**10:00:00** [[Alice]]: Hello world.
"""


def test_enrich_notes_backfills_existing_transcript(tmp_path: Path, monkeypatch):
    """Original test: enrichment produces correct frontmatter and body sections."""
    output_dir = tmp_path / "notes"
    output_dir.mkdir()
    note = output_dir / "2026-06-09_13-50_ops-huddle.md"
    note.write_text(
        """---
title: "Ops Huddle"
tags:
  - "meeting"
  - "transcript"
---
## Summary

**Summary**

- Discussion of Abbott permissions in P10 Operations

**Decisions**

- Add Ava and Brenda to the top-level share

**Action Items**

- James Tomasino will update the onboarding doc

---

## Participants

| Speaker | Identity | Confidence |
|---------|----------|------------|
| [[James Tomasino]] | [[James Tomasino]] | voice_profile |

---

## Decisions



---

## Action Items



---

## Transcript

**13:50:12** [[James Tomasino]]: Can Mike review the current access rules?

**13:50:25** [[Syd Bizovi]]: See https://example.com/doc for the Tymlos share list.
""",
        encoding="utf-8",
    )
    entities = tmp_path / "entities.toml"
    entities.write_text(
        """
[projects."P10 Operations"]
aliases = ["p10 operations"]

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
    config = AppConfig()
    config.output.folder = str(output_dir)
    config.enrichment.entity_catalog_path = str(entities)
    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: config)
    runner = CliRunner()
    result = runner.invoke(cli, ["enrich-notes"], env={})
    assert result.exit_code == 0
    content = note.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert 'related_projects:\n  - "P10 Operations"' in content
    assert 'related_brands:\n  - "Paratek / TYMLOS"' in content
    assert 'related_clients:\n  - "Abbott"\n  - "Paratek"' in content
    assert "## Key Points" in content
    assert "- Discussion of [[Abbott]] permissions in [[P10 Operations]]" in content
    assert "- https://example.com/doc" in content
    assert "for the Tymlos share list." in content
    assert "[[Paratek / TYMLOS]]: See" not in content


def test_is_already_enriched_returns_false_for_unenriched(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text(_BASE_NOTE, encoding="utf-8")
    assert not is_already_enriched(note)


def test_is_already_enriched_returns_true_for_enriched(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text(_ENRICHED_NOTE, encoding="utf-8")
    assert is_already_enriched(note)


def test_get_enriched_at_returns_none_for_unenriched(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text(_BASE_NOTE, encoding="utf-8")
    assert get_enriched_at(note) is None


def test_get_enriched_at_returns_timestamp_for_enriched(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text(_ENRICHED_NOTE, encoding="utf-8")
    assert get_enriched_at(note) == "2026-06-15T12:00:00+00:00"


def test_enrich_notes_skips_already_enriched(tmp_path: Path, monkeypatch):
    """Notes with enriched_at should be skipped on a normal run."""
    output_dir = tmp_path / "notes"
    output_dir.mkdir()

    # One enriched, one not
    enriched = output_dir / "001_enriched.md"
    enriched.write_text(_ENRICHED_NOTE, encoding="utf-8")
    unenriched = output_dir / "002_unenriched.md"
    unenriched.write_text(_BASE_NOTE, encoding="utf-8")

    entities = tmp_path / "entities.toml"
    entities.write_text("", encoding="utf-8")

    config = AppConfig()
    config.output.folder = str(output_dir)
    config.enrichment.entity_catalog_path = str(entities)

    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: config)

    # Mock enrich_note so we don't need LLM
    call_count = 0

    def fake_enrich(*a, **kw):
        nonlocal call_count
        call_count += 1
        from mt_linux.enrichment.models import NoteEnrichment
        return NoteEnrichment()

    monkeypatch.setattr("mt_linux.cli.enrich_note", fake_enrich)

    runner = CliRunner()
    result = runner.invoke(cli, ["enrich-notes"])
    assert result.exit_code == 0
    # Only the unenriched note should be processed
    assert call_count == 1
    assert "Skipped: 1" in result.output


def test_enrich_notes_force_reenriches_all(tmp_path: Path, monkeypatch):
    """--force should process even already-enriched notes."""
    output_dir = tmp_path / "notes"
    output_dir.mkdir()

    note_a = output_dir / "001.md"
    note_a.write_text(_ENRICHED_NOTE, encoding="utf-8")
    note_b = output_dir / "002.md"
    note_b.write_text(_ENRICHED_NOTE, encoding="utf-8")

    entities = tmp_path / "entities.toml"
    entities.write_text("", encoding="utf-8")

    config = AppConfig()
    config.output.folder = str(output_dir)
    config.enrichment.entity_catalog_path = str(entities)

    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: config)

    call_count = 0

    def fake_enrich(*a, **kw):
        nonlocal call_count
        call_count += 1
        from mt_linux.enrichment.models import NoteEnrichment
        return NoteEnrichment()

    monkeypatch.setattr("mt_linux.cli.enrich_note", fake_enrich)

    runner = CliRunner()
    result = runner.invoke(cli, ["enrich-notes", "--force"])
    assert result.exit_code == 0
    assert call_count == 2


def test_enrich_notes_dry_run_no_changes(tmp_path: Path, monkeypatch):
    """--dry-run should report what would happen without modifying files."""
    output_dir = tmp_path / "notes"
    output_dir.mkdir()

    note = output_dir / "001.md"
    note.write_text(_BASE_NOTE, encoding="utf-8")
    original_content = note.read_text(encoding="utf-8")

    entities = tmp_path / "entities.toml"
    entities.write_text("", encoding="utf-8")

    config = AppConfig()
    config.output.folder = str(output_dir)
    config.enrichment.entity_catalog_path = str(entities)

    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: config)

    # enrich_note should never be called in dry-run
    monkeypatch.setattr("mt_linux.cli.enrich_note", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("should not call")))

    runner = CliRunner()
    result = runner.invoke(cli, ["enrich-notes", "--dry-run"])
    assert result.exit_code == 0
    assert "[dry-run]" in result.output
    assert note.read_text(encoding="utf-8") == original_content


def test_enrich_notes_since_skips_recent(tmp_path: Path, monkeypatch):
    """--since should skip notes enriched after the cutoff date."""
    output_dir = tmp_path / "notes"
    output_dir.mkdir()

    # Enriched on June 15 (after June 10 cutoff)
    recent = output_dir / "001_recent.md"
    recent.write_text(_ENRICHED_NOTE, encoding="utf-8")

    # Enriched on June 5 (before June 10 cutoff)
    old_note = """\
---
title: "Old Meeting"
enriched_at: "2026-06-05T08:00:00+00:00"
tags:
  - "meeting"
  - "transcript"
---
## Summary

Old summary.

---

## Participants

| Speaker | Identity | Confidence |
|---------|----------|------------|
| [[Bob]] | [[Bob]] | voice_profile |

---

## Transcript

**09:00:00** [[Bob]]: Old transcript.
"""
    old = output_dir / "002_old.md"
    old.write_text(old_note, encoding="utf-8")

    entities = tmp_path / "entities.toml"
    entities.write_text("", encoding="utf-8")

    config = AppConfig()
    config.output.folder = str(output_dir)
    config.enrichment.entity_catalog_path = str(entities)

    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: config)

    call_count = 0

    def fake_enrich(*a, **kw):
        nonlocal call_count
        call_count += 1
        from mt_linux.enrichment.models import NoteEnrichment
        return NoteEnrichment()

    monkeypatch.setattr("mt_linux.cli.enrich_note", fake_enrich)

    runner = CliRunner()
    result = runner.invoke(cli, ["enrich-notes", "--since", "2026-06-10"])
    assert result.exit_code == 0
    # Only the old note should be processed (enriched before cutoff)
    assert call_count == 1
    assert "Skipped: 1" in result.output


def test_enrich_notes_limit_respects_skip(tmp_path: Path, monkeypatch):
    """--limit counts processed notes, not skipped ones."""
    output_dir = tmp_path / "notes"
    output_dir.mkdir()

    # All enriched so all skipped
    for i in range(5):
        p = output_dir / f"{i:03d}.md"
        p.write_text(_ENRICHED_NOTE, encoding="utf-8")

    entities = tmp_path / "entities.toml"
    entities.write_text("", encoding="utf-8")

    config = AppConfig()
    config.output.folder = str(output_dir)
    config.enrichment.entity_catalog_path = str(entities)

    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: config)

    runner = CliRunner()
    result = runner.invoke(cli, ["enrich-notes", "--limit", "2"])
    assert result.exit_code == 0
    # All skipped, no processing happened
    assert "No transcript notes found." in result.output


def test_get_enriched_at_from_frontmatter_returns_none_for_empty():
    assert get_enriched_at_from_frontmatter("") is None
    assert get_enriched_at_from_frontmatter("---\n---\n") is None


def test_get_enriched_at_from_frontmatter_parses_timestamp():
    fm = '---\nenriched_at: "2026-07-01T10:00:00+00:00"\n---\n'
    assert get_enriched_at_from_frontmatter(fm) == "2026-07-01T10:00:00+00:00"


def test_get_enriched_at_from_frontmatter_handles_unquoted():
    fm = '---\nenriched_at: 2026-07-01T10:00:00+00:00\n---\n'
    assert get_enriched_at_from_frontmatter(fm) == "2026-07-01T10:00:00+00:00"


def test_enrich_notes_force_and_since(tmp_path: Path, monkeypatch):
    """--force with --since: process all notes regardless of enriched_at, but --since is ignored since --force overrides."""
    output_dir = tmp_path / "notes"
    output_dir.mkdir()

    # All enriched after the since cutoff
    for i in range(3):
        p = output_dir / f"{i:03d}.md"
        p.write_text(_ENRICHED_NOTE, encoding="utf-8")

    entities = tmp_path / "entities.toml"
    entities.write_text("", encoding="utf-8")

    config = AppConfig()
    config.output.folder = str(output_dir)
    config.enrichment.entity_catalog_path = str(entities)

    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: config)

    call_count = 0

    def fake_enrich(*a, **kw):
        nonlocal call_count
        call_count += 1
        from mt_linux.enrichment.models import NoteEnrichment
        return NoteEnrichment()

    monkeypatch.setattr("mt_linux.cli.enrich_note", fake_enrich)

    runner = CliRunner()
    result = runner.invoke(cli, ["enrich-notes", "--force", "--since", "2026-06-20"])
    assert result.exit_code == 0
    # --force overrides the skip, so all 3 should be processed
    assert call_count == 3


def test_enrich_notes_dry_run_with_since(tmp_path: Path, monkeypatch):
    """--dry-run with --since should only show notes that would be processed."""
    output_dir = tmp_path / "notes"
    output_dir.mkdir()

    # Enriched before cutoff
    old = output_dir / "001_old.md"
    old.write_text(
        '---\nenriched_at: "2026-06-01T00:00:00+00:00"\n---\n'
        "## Summary\n\nOld.\n\n---\n\n## Participants\n\nnone\n\n---\n\n## Transcript\n\n**10:00** A: hi\n",
        encoding="utf-8",
    )
    # Enriched after cutoff
    recent = output_dir / "002_recent.md"
    recent.write_text(
        '---\nenriched_at: "2026-06-20T00:00:00+00:00"\n---\n'
        "## Summary\n\nRecent.\n\n---\n\n## Participants\n\nnone\n\n---\n\n## Transcript\n\n**10:00** A: hi\n",
        encoding="utf-8",
    )
    # Not enriched at all
    fresh = output_dir / "003_fresh.md"
    fresh.write_text(
        "---\n---\n"
        "## Summary\n\nFresh.\n\n---\n\n## Participants\n\nnone\n\n---\n\n## Transcript\n\n**10:00** A: hi\n",
        encoding="utf-8",
    )

    entities = tmp_path / "entities.toml"
    entities.write_text("", encoding="utf-8")

    config = AppConfig()
    config.output.folder = str(output_dir)
    config.enrichment.entity_catalog_path = str(entities)

    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: config)
    monkeypatch.setattr("mt_linux.cli.enrich_note", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("should not call")))

    runner = CliRunner()
    result = runner.invoke(cli, ["enrich-notes", "--dry-run", "--since", "2026-06-10"])
    assert result.exit_code == 0
    assert "001_old.md" in result.output
    assert "003_fresh.md" in result.output
    assert "002_recent.md" not in result.output
    assert "Skipped: 1" in result.output


def test_enrich_notes_writes_quoted_enriched_at(tmp_path: Path, monkeypatch):
    """Enriched notes should have enriched_at quoted in frontmatter."""
    output_dir = tmp_path / "notes"
    output_dir.mkdir()
    note = output_dir / "001.md"
    note.write_text(_BASE_NOTE, encoding="utf-8")

    entities = tmp_path / "entities.toml"
    entities.write_text("", encoding="utf-8")

    config = AppConfig()
    config.output.folder = str(output_dir)
    config.enrichment.entity_catalog_path = str(entities)

    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: config)

    def fake_enrich(*a, **kw):
        from mt_linux.enrichment.models import NoteEnrichment
        return NoteEnrichment()

    monkeypatch.setattr("mt_linux.cli.enrich_note", fake_enrich)

    runner = CliRunner()
    result = runner.invoke(cli, ["enrich-notes"])
    assert result.exit_code == 0
    content = note.read_text(encoding="utf-8")
    # enriched_at should be quoted
    assert 'enriched_at: "' in content
