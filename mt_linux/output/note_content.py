from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class ParsedNote:
    frontmatter: str
    summary: str
    participants: str
    decisions: str
    action_items: str
    transcript: str


def parse_note_content(content: str) -> ParsedNote:
    frontmatter, body = _split_frontmatter(content)
    return ParsedNote(
        frontmatter=frontmatter,
        summary=_section(body, "Summary"),
        participants=_section(body, "Participants"),
        decisions=_section(body, "Decisions"),
        action_items=_section(body, "Action Items"),
        transcript=_section(body, "Transcript"),
    )


def _split_frontmatter(content: str) -> tuple[str, str]:
    if not content.startswith("---\n"):
        return "", content
    end = content.find("\n---\n", 4)
    if end == -1:
        return "", content
    frontmatter = content[: end + 5]
    body = content[end + 5 :]
    return frontmatter, body


def _section(body: str, title: str) -> str:
    pattern = rf"## {re.escape(title)}\n\n(.*?)(?:\n\n---\n|\Z)"
    match = re.search(pattern, body, flags=re.S)
    return match.group(1).strip() if match else ""
