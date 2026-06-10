from pathlib import Path

from click.testing import CliRunner

from mt_linux.cli import cli
from mt_linux.config import AppConfig


def test_enrich_notes_backfills_existing_transcript(tmp_path: Path, monkeypatch):
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
