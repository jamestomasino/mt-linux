from __future__ import annotations

import json
import logging
import re

from mt_linux.config import AppConfig
from mt_linux.enrichment.models import ActionItem, NoteEnrichment

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^\*\*(Summary|Decisions|Action Items)\*\*\s*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)$")
_URL_RE = re.compile(r"https?://\S+")

_LLM_ENRICHMENT_PROMPT = """Extract structured data from this meeting summary and transcript.
Return ONLY valid JSON with these keys: key_points, decisions, action_items, open_questions.
Each should be an array of strings. action_items should be an array of objects with "text" and "owner" keys.
If a section is not present, use an empty array.

Summary:
{summary}

Transcript:
{transcript}
"""


def extract_protocol_enrichment(
    summary: str,
    transcript: str,
    config: AppConfig | None = None,
) -> NoteEnrichment:
    sections = _split_protocol_sections(summary)
    key_points = _extract_list_items(sections.get("Summary", ""))
    decisions = _extract_list_items(sections.get("Decisions", ""))
    action_items = [_parse_action_item(item) for item in _extract_list_items(sections.get("Action Items", ""))]

    # If regex extraction got nothing useful, try LLM fallback.
    if not key_points and not decisions and not action_items and config is not None:
        llm_result = _try_llm_enrichment(summary, transcript, config)
        if llm_result is not None:
            key_points, decisions, action_items = llm_result

    links = sorted(set(_URL_RE.findall(f"{summary}\n{transcript}")))
    open_questions = _extract_open_questions(transcript)
    tags = _derive_tags(key_points, decisions, action_items)
    return NoteEnrichment(
        key_points=key_points,
        decisions=decisions,
        action_items=action_items,
        open_questions=open_questions,
        links_mentioned=links,
        tags=tags,
    )


def _split_protocol_sections(summary: str) -> dict[str, str]:
    matches = list(_HEADING_RE.finditer(summary))
    if not matches:
        return {"Summary": summary.strip()}
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(summary)
        sections[match.group(1)] = summary[start:end].strip()
    return sections


def _extract_list_items(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        match = _BULLET_RE.match(line.strip())
        if match:
            item = match.group(1).strip()
            if item:
                items.append(item)
    return items


def _parse_action_item(text: str) -> ActionItem:
    owner = ""
    cleaned = text.strip()
    colon_match = re.match(r"^\[\[(.+?)\]\]:(.*)$", cleaned)
    if colon_match:
        owner = colon_match.group(1).strip()
        cleaned = colon_match.group(2).strip()
    else:
        will_match = re.match(r"^\[\[(.+?)\]\]\s+will\s+(.*)$", cleaned, flags=re.I)
        if will_match:
            owner = will_match.group(1).strip()
            cleaned = will_match.group(2).strip()
        else:
            plain_match = re.match(r"^([A-Z][A-Za-z .'-]+?)\s+will\s+(.*)$", cleaned)
            if plain_match:
                owner = plain_match.group(1).strip()
                cleaned = plain_match.group(2).strip()
    return ActionItem(text=cleaned, owner=owner)


def _extract_open_questions(transcript: str) -> list[str]:
    questions: list[str] = []
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if "?" not in line:
            continue
        parts = line.split(":", 1)
        question = parts[1].strip() if len(parts) == 2 else line
        if question and question not in questions:
            questions.append(question)
    return questions[:10]


def _derive_tags(
    key_points: list[str],
    decisions: list[str],
    action_items: list[ActionItem],
) -> list[str]:
    tags = {"meeting", "transcript"}
    text = " ".join(key_points + decisions + [item.text for item in action_items]).lower()
    for keyword in ("permissions", "drive", "onboarding", "access", "calendar", "zoom", "teams", "slack"):
        if keyword in text:
            tags.add(keyword)
    return sorted(tags)


def _sentences(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    return parts[:6]


def _try_llm_enrichment(
    summary: str,
    transcript: str,
    config: AppConfig,
) -> tuple[list[str], list[str], list[ActionItem]] | None:
    """Fallback: use OpenAI-compatible endpoint to extract structured enrichment data."""
    openai_cfg = config.openai
    if not openai_cfg.enabled or not openai_cfg.api_key:
        return None

    prompt = _LLM_ENRICHMENT_PROMPT.format(
        summary=summary[:4000],
        transcript=transcript[:6000],
    )
    payload = {
        "model": openai_cfg.model or "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are a structured data extraction assistant. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
    }
    try:
        import httpx

        response = httpx.post(
            openai_cfg.endpoint,
            json=payload,
            timeout=120,
            headers={"Authorization": f"Bearer {openai_cfg.api_key}"},
        )
        response.raise_for_status()
        data = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(data)
        key_points = parsed.get("key_points", [])
        decisions = parsed.get("decisions", [])
        raw_actions = parsed.get("action_items", [])
        action_items = [
            ActionItem(text=item.get("text", ""), owner=item.get("owner", ""))
            for item in raw_actions
            if isinstance(item, dict) and item.get("text")
        ]
        return key_points, decisions, action_items
    except Exception:
        logger.debug("LLM enrichment fallback failed", exc_info=True)
        return None
