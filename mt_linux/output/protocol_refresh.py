from __future__ import annotations

from pathlib import Path
import re

from mt_linux.config import AppConfig
from mt_linux.enrichment.entities import linkify_entity_mentions
from mt_linux.enrichment.service import load_entity_catalog
from mt_linux.models import MeetingInfo
from mt_linux.protocol.ollama_generator import OllamaProtocolGenerator


SUMMARY_HEADING = "## Summary\n\n"
TRANSCRIPT_HEADING = "## Transcript\n\n"


def refresh_summary_from_transcript(
    path: Path,
    config: AppConfig,
    meeting_info: MeetingInfo,
) -> bool:
    if not config.protocol.enabled or not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    transcript = extract_protocol_transcript(content)
    if not transcript.strip():
        return False
    generator = OllamaProtocolGenerator(config.protocol)
    summary = sanitize_summary_placeholders(generator.generate(transcript, meeting_info).strip())
    if not summary:
        return False
    if config.enrichment.enabled:
        summary = linkify_entity_mentions(summary, load_entity_catalog(config))
    updated = replace_summary_section(content, summary)
    path.write_text(updated, encoding="utf-8")
    return True


def extract_protocol_transcript(content: str) -> str:
    if TRANSCRIPT_HEADING not in content:
        return ""
    transcript = content.split(TRANSCRIPT_HEADING, 1)[1].strip()
    lines: list[str] = []
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^\*\*\d{2}:\d{2}:\d{2}\*\*\s+(.*)$", line)
        if match:
            lines.append(match.group(1))
        else:
            lines.append(line)
    return "\n".join(lines)


def replace_summary_section(content: str, summary: str) -> str:
    pattern = r"## Summary\n\n.*?\n\n---\n"
    replacement = f"{SUMMARY_HEADING}{summary}\n\n---\n"
    return re.sub(pattern, replacement, content, count=1, flags=re.S)


def sanitize_summary_placeholders(summary: str) -> str:
    cleaned_lines: list[str] = []
    for line in summary.splitlines():
        cleaned = re.sub(
            r"^(\s*(?:[-*]|\d+\.)\s+)\[(?:Name|Person|Unknown Speaker|TBD)\]\s+will\s+",
            r"\1",
            line,
            flags=re.I,
        )
        cleaned_lines.append(cleaned)
    return "\n".join(cleaned_lines).strip()
