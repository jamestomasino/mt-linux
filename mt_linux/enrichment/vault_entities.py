from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass
class VaultEntity:
    name: str
    entity_type: str
    aliases: list[str]
    clients: list[str]
    brands: list[str]


def default_entity_notes_root(transcript_output_dir: Path) -> Path:
    return transcript_output_dir.parent / "Entities"


def load_vault_entities(root: Path) -> list[VaultEntity]:
    if not root.exists():
        return []
    entities: list[VaultEntity] = []
    for path in sorted(root.rglob("*.md")):
        entity = _parse_entity_note(path)
        if entity is not None:
            entities.append(entity)
    return entities


def write_entity_catalog(root: Path, target: Path) -> None:
    entities = load_vault_entities(root)
    projects = [entity for entity in entities if entity.entity_type == "project"]
    brands = [entity for entity in entities if entity.entity_type == "brand"]
    clients = [entity for entity in entities if entity.entity_type == "client"]
    lines: list[str] = []
    lines.extend(_toml_group("projects", projects))
    if lines:
        lines.append("")
    lines.extend(_toml_group("brands", brands))
    if lines:
        lines.append("")
    lines.extend(_toml_group("clients", clients))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _parse_entity_note(path: Path) -> VaultEntity | None:
    content = path.read_text(encoding="utf-8")
    frontmatter = _frontmatter(content)
    if not frontmatter:
        return None
    entity_type = frontmatter.get("entity_type", "").strip().lower()
    if entity_type not in {"client", "project", "brand"}:
        return None
    name = frontmatter.get("title", "").strip() or path.stem
    aliases = _frontmatter_list(frontmatter, "aliases")
    aliases = [alias for alias in [name, *aliases] if alias]
    aliases = list(dict.fromkeys(aliases))
    clients = _frontmatter_list(frontmatter, "client") or _frontmatter_list(frontmatter, "clients")
    brands = _frontmatter_list(frontmatter, "brands")
    return VaultEntity(
        name=name,
        entity_type=entity_type,
        aliases=aliases,
        clients=clients,
        brands=brands,
    )


def _frontmatter(content: str) -> dict[str, str]:
    if not content.startswith("---\n"):
        return {}
    end = content.find("\n---\n", 4)
    if end == -1:
        return {}
    block = content[4:end]
    result: dict[str, str] = {}
    current_key = ""
    list_lines: list[str] = []
    for raw_line in block.splitlines():
        if raw_line.startswith("  - ") and current_key:
            list_lines.append(raw_line[4:].strip().strip('"'))
            result[current_key] = "\n".join(list_lines)
            continue
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        current_key = key.strip()
        list_lines = []
        result[current_key] = value.strip().strip('"')
    return result


def _frontmatter_list(frontmatter: dict[str, str], key: str) -> list[str]:
    value = frontmatter.get(key, "")
    if not value:
        return []
    return [_normalize_link(line.strip().strip('"')) for line in value.splitlines() if line.strip()]


def _toml_group(name: str, entities: list[VaultEntity]) -> list[str]:
    lines: list[str] = []
    for entity in entities:
        lines.append(f'[{name}."{entity.name}"]')
        aliases = ", ".join(_toml_string(alias) for alias in entity.aliases[1:])
        lines.append(f"aliases = [{aliases}]")
        if entity.clients:
            clients = ", ".join(_toml_string(client) for client in entity.clients)
            lines.append(f"clients = [{clients}]")
        if entity.brands:
            brands = ", ".join(_toml_string(brand) for brand in entity.brands)
            lines.append(f"brands = [{brands}]")
        lines.append("")
    return lines[:-1] if lines else lines


def _toml_string(value: str) -> str:
    escaped = re.sub(r'(["\\\\])', r"\\\1", value)
    return f'"{escaped}"'


def _normalize_link(value: str) -> str:
    if value.startswith("[[") and value.endswith("]]"):
        return value[2:-2].strip()
    return value
