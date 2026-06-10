from pathlib import Path

from click.testing import CliRunner

from mt_linux.cli import cli
from mt_linux.config import AppConfig
from mt_linux.enrichment.service import entity_notes_root, sync_entity_catalog
from mt_linux.enrichment.vault_entities import load_vault_entities, write_entity_catalog


def test_write_entity_catalog_from_vault_notes(tmp_path: Path):
    root = tmp_path / "Entities"
    root.mkdir(parents=True)
    (root / "Paratek.md").write_text(
        """---
title: "Paratek"
entity_type: "client"
aliases:
  - "paratek"
  - "paratech"
---
""",
        encoding="utf-8",
    )
    (root / "TYMLOS.md").write_text(
        """---
title: "Paratek / TYMLOS"
entity_type: "brand"
aliases:
  - "tymlos"
client:
  - "[[Paratek]]"
---
""",
        encoding="utf-8",
    )
    target = tmp_path / "entities.toml"
    write_entity_catalog(root, target)
    content = target.read_text(encoding="utf-8")
    assert '[brands."Paratek / TYMLOS"]' in content
    assert '[clients."Paratek"]' in content
    assert '"paratech"' in content
    assert 'clients = ["Paratek"]' in content


def test_sync_entities_command_uses_default_vault_root(tmp_path: Path, monkeypatch):
    notes_root = tmp_path / "Entities"
    notes_root.mkdir(parents=True)
    (notes_root / "LEO.md").write_text(
        """---
title: "LEO"
entity_type: "client"
aliases:
  - "leo"
---
""",
        encoding="utf-8",
    )
    output_dir = tmp_path / "transcripts"
    output_dir.mkdir()
    config = AppConfig()
    config.output.folder = str(output_dir)
    config.enrichment.entity_catalog_path = str(tmp_path / "entities.toml")
    monkeypatch.setattr("mt_linux.cli.AppConfig.load", lambda: config)
    runner = CliRunner()
    result = runner.invoke(cli, ["sync-entities"], env={})
    assert result.exit_code == 0
    assert 'Catalog: ' in result.output
    content = Path(config.enrichment.entity_catalog_path).read_text(encoding="utf-8")
    assert '[clients."LEO"]' in content


def test_load_vault_entities_reads_links_and_brand_relationships(tmp_path: Path):
    root = tmp_path / "Entities"
    root.mkdir(parents=True)
    note = root / "brand.md"
    note.write_text(
        """---
title: "Paratek / TYMLOS"
entity_type: "brand"
aliases:
  - "tymlos"
client:
  - "[[Paratek]]"
---
""",
        encoding="utf-8",
    )
    entities = load_vault_entities(root)
    assert entities[0].entity_type == "brand"
    assert entities[0].clients == ["Paratek"]


def test_entity_notes_root_prefers_vault_root(tmp_path: Path):
    config = AppConfig()
    config.output.folder = str(tmp_path / "Meetings")
    config.output.vault_root = str(tmp_path)
    assert entity_notes_root(config) == tmp_path / "Entities"
