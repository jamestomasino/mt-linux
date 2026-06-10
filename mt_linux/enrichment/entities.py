from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import tomllib

from mt_linux.enrichment.models import NoteEnrichment


@dataclass
class EntityRecord:
    aliases: list[str] = field(default_factory=list)
    clients: list[str] = field(default_factory=list)
    brands: list[str] = field(default_factory=list)


@dataclass
class EntityCatalog:
    projects: dict[str, EntityRecord] = field(default_factory=dict)
    brands: dict[str, EntityRecord] = field(default_factory=dict)
    clients: dict[str, EntityRecord] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "EntityCatalog":
        if not path.exists():
            return cls()
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        return cls(
            projects=_read_entity_group(data.get("projects", {})),
            brands=_read_entity_group(data.get("brands", {})),
            clients=_read_entity_group(data.get("clients", {})),
        )

    def all_link_targets(self) -> list[tuple[str, str]]:
        seen: set[tuple[str, str]] = set()
        ordered: list[tuple[str, str]] = []
        for group in (self.brands, self.projects, self.clients):
            for canonical, record in group.items():
                for alias in record.aliases:
                    key = (alias.lower(), canonical)
                    if key in seen:
                        continue
                    seen.add(key)
                    ordered.append((alias, canonical))
        ordered.sort(key=lambda item: len(item[0]), reverse=True)
        return ordered


def apply_entity_matches(enrichment: NoteEnrichment, text: str, catalog: EntityCatalog) -> NoteEnrichment:
    projects = _match_entities(text, catalog.projects)
    brands = _match_entities(text, catalog.brands)
    clients = _match_entities(text, catalog.clients)
    clients = _merge_related_clients(clients, projects, catalog.projects, brands, catalog.brands)
    tags = set(enrichment.tags)
    tags.update(_slugify(name) for name in projects)
    tags.update(_slugify(name) for name in brands)
    tags.update(_slugify(name) for name in clients)
    return NoteEnrichment(
        key_points=enrichment.key_points,
        decisions=enrichment.decisions,
        action_items=enrichment.action_items,
        open_questions=enrichment.open_questions,
        links_mentioned=enrichment.links_mentioned,
        related_projects=projects,
        related_brands=brands,
        related_clients=clients,
        tags=sorted(tags),
    )


def linkify_entity_mentions(text: str, catalog: EntityCatalog) -> str:
    if not text.strip():
        return text
    aliases = catalog.all_link_targets()
    if not aliases:
        return text
    protected, placeholders = _protect_wikilinks(text)
    alias_map = {alias.lower(): canonical for alias, canonical in aliases}
    pattern = re.compile(
        "|".join(
            rf"(?<![\w\]]){re.escape(alias)}(?![\w\[])"
            for alias, _canonical in aliases
        ),
        flags=re.IGNORECASE,
    )

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        canonical = alias_map.get(raw.lower())
        if canonical is None:
            return raw
        return f"[[{canonical}]]"

    linked = pattern.sub(_replace, protected)
    return _restore_wikilinks(linked, placeholders)


def _read_entity_group(data: dict) -> dict[str, EntityRecord]:
    result: dict[str, EntityRecord] = {}
    for name, value in data.items():
        aliases = value.get("aliases", []) if isinstance(value, dict) else []
        clients = value.get("clients", []) if isinstance(value, dict) else []
        brands = value.get("brands", []) if isinstance(value, dict) else []
        result[name] = EntityRecord(
            aliases=[name, *aliases],
            clients=list(clients),
            brands=list(brands),
        )
    return result


def _match_entities(text: str, entities: dict[str, EntityRecord]) -> list[str]:
    found: list[str] = []
    lowered = text.lower()
    for canonical, record in entities.items():
        for alias in record.aliases:
            pattern = rf"\b{re.escape(alias.lower())}\b"
            if re.search(pattern, lowered):
                found.append(canonical)
                break
    return sorted(dict.fromkeys(found))


def _merge_related_clients(
    direct_clients: list[str],
    projects: list[str],
    project_records: dict[str, EntityRecord],
    brands: list[str],
    brand_records: dict[str, EntityRecord],
) -> list[str]:
    clients = list(direct_clients)
    for project in projects:
        clients.extend(project_records.get(project, EntityRecord()).clients)
    for brand in brands:
        clients.extend(brand_records.get(brand, EntityRecord()).clients)
    return sorted(dict.fromkeys(client for client in clients if client))


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _protect_wikilinks(text: str) -> tuple[str, dict[str, str]]:
    placeholders: dict[str, str] = {}

    def _replace(match: re.Match[str]) -> str:
        token = f"__WIKILINK_{len(placeholders)}__"
        placeholders[token] = match.group(0)
        return token

    return re.sub(r"\[\[[^\]]+\]\]", _replace, text), placeholders


def _restore_wikilinks(text: str, placeholders: dict[str, str]) -> str:
    restored = text
    for token, value in placeholders.items():
        restored = restored.replace(token, value)
    return restored
