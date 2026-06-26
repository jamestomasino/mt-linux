"""LLM-powered entity discovery, spell checking, and topic extraction."""

from __future__ import annotations

import json
import logging
import re

from mt_linux.config import AppConfig
from mt_linux.enrichment.entities import EntityCatalog
from mt_linux.enrichment.models import (
    DiscoveredEntity,
    MeetingQuality,
    MeetingTopic,
    NoteEnrichment,
    SpellCorrection,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

_DISCOVERY_PROMPT = """You are an advanced entity and topic extraction assistant.
Analyze the following meeting transcript and summary and extract structured data.

Return ONLY valid JSON with these keys:
- discovered_entities: array of objects with keys "name", "entity_type", "confidence", "context", "relationships"
  entity_type can be: person, organization, location, product, document, deadline, concept
  Only include entities NOT already in the known catalog.
- spell_corrections: array of objects with keys "original", "corrected", "entity_type", "confidence"
  Identify misspellings of known entities (names, brands, projects, organizations).
- meeting_topics: array of objects with keys "name", "weight", "related_entities"
  Extract 3-8 high-level topics discussed.
- sentiment: one of "positive", "neutral", "negative", "mixed"
- key_people: array of strings - people mentioned who are not direct participants
- deadlines_mentioned: array of strings - specific deadlines, dates, or timeframes mentioned
- documents_mentioned: array of strings - documents, reports, assets, or deliverables mentioned
- meeting_quality: object with keys "overall_score" (0-1), "audio_quality" (good/fair/poor/unknown),
  "gaps" (array of strings describing issues), "speaker_coverage" (0-1),
  "recommendations" (array of strings)

Known entity catalog (do NOT re-discover these):
{catalog}

Summary:
{summary}

Transcript:
{transcript}
"""

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enrich_with_llm(
    summary: str,
    transcript: str,
    config: AppConfig,
    catalog: EntityCatalog,
    enrichment: NoteEnrichment,
) -> NoteEnrichment:
    """Run LLM-based enrichment pass on the note content.

    Tries the local Ollama/protocol backend first, falls back to OpenAI.
    """
    openai_cfg = config.openai
    protocol_cfg = config.protocol

    catalog_text = _build_catalog_text(catalog)
    prompt = _DISCOVERY_PROMPT.format(
        catalog=catalog_text[:3000],
        summary=summary[:3000],
        transcript=transcript[:6000],
    )

    system_content = (
        "You are an advanced entity extraction and analysis assistant. "
        "Return only valid JSON matching the requested schema. "
        "Be precise - do not hallucinate entities."
    )

    # Try local Ollama/protocol backend first
    if protocol_cfg.enabled:
        result = _try_ollama_enrichment(protocol_cfg, prompt, system_content)
        if result is not None:
            return _apply_llm_results(enrichment, result)

    # Fallback to OpenAI
    if openai_cfg.enabled and openai_cfg.api_key:
        result = _try_openai_enrichment(openai_cfg, prompt, system_content)
        if result is not None:
            return _apply_llm_results(enrichment, result)

    return enrichment


def _try_ollama_enrichment(
    protocol_cfg,
    prompt: str,
    system_content: str,
) -> dict | None:
    """Try enrichment via the local Ollama-compatible endpoint."""
    try:
        import httpx

        payload = {
            "model": protocol_cfg.model or "gemma2:27b",
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        response = httpx.post(
            protocol_cfg.endpoint,
            json=payload,
            timeout=180,
        )
        response.raise_for_status()
        data = response.json()["choices"][0]["message"]["content"]
        return json.loads(data)
    except Exception:
        logger.debug("Ollama enrichment discovery pass failed", exc_info=True)
        return None


def _try_openai_enrichment(
    openai_cfg,
    prompt: str,
    system_content: str,
) -> dict | None:
    """Try enrichment via the OpenAI-compatible endpoint."""
    try:
        import httpx

        payload = {
            "model": openai_cfg.model or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        response = httpx.post(
            openai_cfg.endpoint,
            json=payload,
            timeout=180,
            headers={"Authorization": f"Bearer {openai_cfg.api_key}"},
        )
        response.raise_for_status()
        data = response.json()["choices"][0]["message"]["content"]
        return json.loads(data)
    except Exception:
        logger.debug("OpenAI enrichment discovery pass failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Local spell checking (no LLM required)
# ---------------------------------------------------------------------------


def check_spelling(text: str, catalog: EntityCatalog) -> list[SpellCorrection]:
    """Detect misspellings of known entities using fuzzy matching.

    This runs locally without an LLM call and catches common transcription
    errors like 'Timlos' -> 'TYMLOS' or 'Paratech' -> 'Paratek'.
    """
    corrections: list[SpellCorrection] = []
    seen: set[tuple[str, str]] = set()

    # Build a map of all known entity names + aliases -> canonical form
    all_entities: list[tuple[str, str, str]] = []  # (alias_lower, canonical, entity_type)
    for entity_type, group in [
        ("project", catalog.projects),
        ("brand", catalog.brands),
        ("client", catalog.clients),
    ]:
        for canonical, record in group.items():
            for alias in record.aliases:
                all_entities.append((alias.lower(), canonical, entity_type))

    # Sort by length descending so we match longer strings first
    all_entities.sort(key=lambda x: len(x[0]), reverse=True)

    # Find all words/phrases in the text that are close to known entities
    text_lower = text.lower()
    for alias_lower, canonical, entity_type in all_entities:
        if alias_lower in text_lower:
            continue  # Exact match, no correction needed

        # Check for fuzzy matches using simple edit distance
        # We look for substrings in the text that are close to the alias
        _find_fuzzy_matches(text_lower, alias_lower, canonical, entity_type, corrections, seen)

    return corrections


def _find_fuzzy_matches(
    text_lower: str,
    alias_lower: str,
    canonical: str,
    entity_type: str,
    corrections: list[SpellCorrection],
    seen: set[tuple[str, str]],
) -> None:
    """Find fuzzy matches of alias in text and add corrections."""
    alias_len = len(alias_lower)
    if alias_len < 3:
        return

    # Sliding window over the text
    for i in range(len(text_lower) - alias_len + 1):
        window = text_lower[i : i + alias_len]
        distance = _levenshtein_distance(window, alias_lower)
        # Threshold: allow 1-2 edits depending on length
        max_edits = max(1, min(2, alias_len // 4))
        if distance <= max_edits and distance > 0:
            # Extract the word boundary around this match
            word_start = i
            while word_start > 0 and not text_lower[word_start - 1].isspace() and text_lower[word_start - 1] not in ".,;:!?":
                word_start -= 1
            word_end = i + alias_len
            while word_end < len(text_lower) and (text_lower[word_end].isalnum() or text_lower[word_end] in "'-"):
                word_end += 1
            original_word = text_lower[word_start:word_end]
            key = (original_word, canonical)
            if key not in seen and original_word != alias_lower:
                seen.add(key)
                confidence = 1.0 - (distance / max(1, alias_len))
                corrections.append(
                    SpellCorrection(
                        original=original_word,
                        corrected=canonical,
                        entity_type=entity_type,
                        confidence=round(confidence, 2),
                    )
                )
            break  # Only report once per alias


def _levenshtein_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) < len(b):
        return _levenshtein_distance(b, a)
    if len(b) == 0:
        return len(a)

    prev_row = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr_row = [i + 1]
        for j, cb in enumerate(b):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (ca != cb)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def apply_spell_corrections(text: str, corrections: list[SpellCorrection]) -> str:
    """Apply spell corrections to text. Only correct high-confidence matches."""
    for correction in sorted(corrections, key=lambda c: len(c.original), reverse=True):
        if correction.confidence < 0.5:
            continue
        # Case-insensitive replacement preserving surrounding context
        pattern = re.compile(re.escape(correction.original), re.IGNORECASE)
        text = pattern.sub(correction.corrected, text)
    return text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_catalog_text(catalog: EntityCatalog) -> str:
    """Build a human-readable catalog summary for the LLM prompt."""
    parts: list[str] = []
    for entity_type, group in [
        ("Projects", catalog.projects),
        ("Brands", catalog.brands),
        ("Clients", catalog.clients),
    ]:
        if not group:
            continue
        items = []
        for canonical, record in group.items():
            aliases = record.aliases[1:] if len(record.aliases) > 1 else []
            if aliases:
                items.append(f"  - {canonical} (aka: {', '.join(aliases)})")
            else:
                items.append(f"  - {canonical}")
        parts.append(f"{entity_type}:\n" + "\n".join(items))
    return "\n\n".join(parts) if parts else "(empty catalog)"


def _apply_llm_results(enrichment: NoteEnrichment, parsed: dict) -> NoteEnrichment:
    """Merge LLM results into the existing enrichment object."""
    # Discovered entities
    if parsed.get("discovered_entities"):
        enrichment.discovered_entities = [
            DiscoveredEntity(
                name=e.get("name", ""),
                entity_type=e.get("entity_type", "concept"),
                confidence=float(e.get("confidence", 1.0)),
                context=e.get("context", ""),
                relationships=e.get("relationships", []),
            )
            for e in parsed["discovered_entities"]
            if isinstance(e, dict) and e.get("name")
        ]

    # Spell corrections
    if parsed.get("spell_corrections"):
        llm_corrections = [
            SpellCorrection(
                original=c.get("original", ""),
                corrected=c.get("corrected", ""),
                entity_type=c.get("entity_type", ""),
                confidence=float(c.get("confidence", 1.0)),
            )
            for c in parsed["spell_corrections"]
            if isinstance(c, dict) and c.get("original") and c.get("corrected")
        ]
        # Merge with local spell corrections, deduplicate
        existing_keys = {(sc.original, sc.corrected) for sc in enrichment.spell_corrections}
        for sc in llm_corrections:
            if (sc.original, sc.corrected) not in existing_keys:
                enrichment.spell_corrections.append(sc)

    # Meeting topics
    if parsed.get("meeting_topics"):
        enrichment.meeting_topics = [
            MeetingTopic(
                name=t.get("name", ""),
                weight=float(t.get("weight", 1.0)),
                related_entities=t.get("related_entities", []),
            )
            for t in parsed["meeting_topics"]
            if isinstance(t, dict) and t.get("name")
        ]

    # Sentiment
    if parsed.get("sentiment"):
        enrichment.sentiment = parsed["sentiment"]

    # Key people
    if parsed.get("key_people"):
        enrichment.key_people = [p for p in parsed["key_people"] if isinstance(p, str) and p]

    # Deadlines
    if parsed.get("deadlines_mentioned"):
        enrichment.deadlines_mentioned = [
            d for d in parsed["deadlines_mentioned"] if isinstance(d, str) and d
        ]

    # Documents
    if parsed.get("documents_mentioned"):
        enrichment.documents_mentioned = [
            d for d in parsed["documents_mentioned"] if isinstance(d, str) and d
        ]

    # Meeting quality
    if parsed.get("meeting_quality"):
        mq = parsed["meeting_quality"]
        enrichment.meeting_quality = MeetingQuality(
            overall_score=float(mq.get("overall_score", 1.0)),
            audio_quality=mq.get("audio_quality", "unknown"),
            gaps=mq.get("gaps", []),
            speaker_coverage=float(mq.get("speaker_coverage", 1.0)),
            recommendations=mq.get("recommendations", []),
        )

    # Enhance tags from topics
    if enrichment.meeting_topics:
        topic_tags = set()
        for topic in enrichment.meeting_topics:
            tag = re.sub(r"[^a-z0-9]+", "-", topic.name.lower()).strip("-")
            if tag:
                topic_tags.add(tag)
        existing_tags = set(enrichment.tags)
        enrichment.tags = sorted(existing_tags | topic_tags)

    return enrichment
