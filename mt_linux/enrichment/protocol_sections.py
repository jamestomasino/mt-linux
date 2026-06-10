from __future__ import annotations

import re

from mt_linux.enrichment.models import ActionItem, NoteEnrichment


_HEADING_RE = re.compile(r"^\*\*(Summary|Decisions|Action Items)\*\*\s*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)$")
_URL_RE = re.compile(r"https?://\S+")


def extract_protocol_enrichment(summary: str, transcript: str) -> NoteEnrichment:
    sections = _split_protocol_sections(summary)
    key_points = _extract_list_items(sections.get("Summary", ""))
    if not key_points and sections.get("Summary", "").strip():
        key_points = _sentences(sections["Summary"])
    decisions = _extract_list_items(sections.get("Decisions", ""))
    action_items = [_parse_action_item(item) for item in _extract_list_items(sections.get("Action Items", ""))]
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
