from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ActionItem:
    text: str
    owner: str = ""
    status: str = "open"
    due: str = ""


@dataclass
class NoteEnrichment:
    key_points: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    links_mentioned: list[str] = field(default_factory=list)
    related_projects: list[str] = field(default_factory=list)
    related_brands: list[str] = field(default_factory=list)
    related_clients: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_points": self.key_points,
            "decisions": self.decisions,
            "action_items": [asdict(item) for item in self.action_items],
            "open_questions": self.open_questions,
            "links_mentioned": self.links_mentioned,
            "related_projects": self.related_projects,
            "related_brands": self.related_brands,
            "related_clients": self.related_clients,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NoteEnrichment":
        return cls(
            key_points=list(data.get("key_points", [])),
            decisions=list(data.get("decisions", [])),
            action_items=[ActionItem(**item) for item in data.get("action_items", [])],
            open_questions=list(data.get("open_questions", [])),
            links_mentioned=list(data.get("links_mentioned", [])),
            related_projects=list(data.get("related_projects", [])),
            related_brands=list(data.get("related_brands", [])),
            related_clients=list(data.get("related_clients", [])),
            tags=list(data.get("tags", [])),
        )
