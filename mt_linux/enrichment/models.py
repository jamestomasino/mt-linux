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
class DiscoveredEntity:
    """An entity discovered by the LLM enrichment pass."""
    name: str
    entity_type: str  # person, organization, location, product, document, deadline, concept
    confidence: float = 1.0
    context: str = ""
    """Brief context snippet explaining why this entity was extracted."""
    relationships: list[str] = field(default_factory=list)
    """Related entity names, e.g. ['LEO', 'ANZUPGO'] meaning this entity relates to those."""


@dataclass
class SpellCorrection:
    """A detected misspelling with its correction."""
    original: str
    corrected: str
    entity_type: str = ""
    confidence: float = 1.0


@dataclass
class MeetingTopic:
    """A topic extracted from the meeting."""
    name: str
    weight: float = 1.0
    related_entities: list[str] = field(default_factory=list)


@dataclass
class MeetingQuality:
    """Quality metrics for the transcript/meeting."""
    overall_score: float = 1.0
    """0-1 score: 1 = excellent, 0 = poor."""
    audio_quality: str = "unknown"
    """good, fair, poor, unknown."""
    gaps: list[str] = field(default_factory=list)
    """Descriptions of transcript gaps or issues."""
    speaker_coverage: float = 1.0
    """Fraction of audio time with identified speakers."""
    recommendations: list[str] = field(default_factory=list)
    """Suggestions for improving future meetings or recordings."""


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

    # --- New fields for enhanced enrichment ---
    discovered_entities: list[DiscoveredEntity] = field(default_factory=list)
    spell_corrections: list[SpellCorrection] = field(default_factory=list)
    meeting_topics: list[MeetingTopic] = field(default_factory=list)
    meeting_quality: MeetingQuality | None = None
    related_meetings: list[str] = field(default_factory=list)
    """Session IDs or filenames of related meetings."""
    sentiment: str = "neutral"
    """Overall meeting sentiment: positive, neutral, negative, mixed."""
    key_people: list[str] = field(default_factory=list)
    """People mentioned who are not direct participants."""
    deadlines_mentioned: list[str] = field(default_factory=list)
    """Deadlines or dates mentioned in the meeting."""
    documents_mentioned: list[str] = field(default_factory=list)
    """Documents, reports, or assets mentioned."""

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
            "discovered_entities": [asdict(e) for e in self.discovered_entities],
            "spell_corrections": [asdict(c) for c in self.spell_corrections],
            "meeting_topics": [asdict(t) for t in self.meeting_topics],
            "meeting_quality": asdict(self.meeting_quality) if self.meeting_quality else None,
            "related_meetings": self.related_meetings,
            "sentiment": self.sentiment,
            "key_people": self.key_people,
            "deadlines_mentioned": self.deadlines_mentioned,
            "documents_mentioned": self.documents_mentioned,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NoteEnrichment":
        enrichment = cls(
            key_points=list(data.get("key_points", [])),
            decisions=list(data.get("decisions", [])),
            action_items=[ActionItem(**item) for item in data.get("action_items", [])],
            open_questions=list(data.get("open_questions", [])),
            links_mentioned=list(data.get("links_mentioned", [])),
            related_projects=list(data.get("related_projects", [])),
            related_brands=list(data.get("related_brands", [])),
            related_clients=list(data.get("related_clients", [])),
            tags=list(data.get("tags", [])),
            sentiment=data.get("sentiment", "neutral"),
            key_people=list(data.get("key_people", [])),
            deadlines_mentioned=list(data.get("deadlines_mentioned", [])),
            documents_mentioned=list(data.get("documents_mentioned", [])),
            related_meetings=list(data.get("related_meetings", [])),
        )
        if data.get("discovered_entities"):
            enrichment.discovered_entities = [
                DiscoveredEntity(**item) for item in data["discovered_entities"]
            ]
        if data.get("spell_corrections"):
            enrichment.spell_corrections = [
                SpellCorrection(**item) for item in data["spell_corrections"]
            ]
        if data.get("meeting_topics"):
            enrichment.meeting_topics = [
                MeetingTopic(**item) for item in data["meeting_topics"]
            ]
        if data.get("meeting_quality"):
            enrichment.meeting_quality = MeetingQuality(**data["meeting_quality"])
        return enrichment
