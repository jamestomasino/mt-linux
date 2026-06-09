from __future__ import annotations

from pathlib import Path
import re

from mt_linux.models import CalendarEvent


def replace_speaker_label(path: Path, speaker_label: str, speaker_name: str) -> None:
    content = path.read_text(encoding="utf-8")
    wikified = f"[[{speaker_name}]]"
    content = content.replace(f"[[{speaker_label}]]", wikified)
    content = content.replace(speaker_label, wikified)
    content = re.sub(
        rf'(name:\s*"{re.escape(wikified)}"\n\s*confidence:\s*)"unidentified"',
        r'\1"voice_profile"',
        content,
    )
    content = content.replace("\n    review_queued: true", "")
    content = _dedupe_participants(content)
    content = _dedupe_participants_identified(content)
    content = _dedupe_participants_table(content)
    path.write_text(content, encoding="utf-8")


def apply_meeting_assignment(
    path: Path,
    selected_event: CalendarEvent,
    candidates: list[CalendarEvent],
    ambiguous: bool,
) -> None:
    content = path.read_text(encoding="utf-8")
    content = _replace_scalar(content, "calendar_event_id", selected_event.event_id)
    content = _replace_scalar(content, "calendar_match_confidence", "ambiguous" if ambiguous else "matched")
    content = _replace_scalar(content, "calendar_review_queued", "false", quoted=False)
    content = _replace_scalar(content, "title", selected_event.title)
    content = _replace_scalar(content, "organizer", f"[[{selected_event.organizer}]]" if selected_event.organizer else "")
    duration_minutes = int((selected_event.end_time - selected_event.start_time).total_seconds() // 60)
    content = _replace_scalar(content, "duration_minutes", str(duration_minutes), quoted=False)
    content = _replace_block(content, "calendar_candidate_event_ids", [f'  - "{selected_event.event_id}"'])
    attendee_lines = [f'  - "{attendee.display()}"' for attendee in selected_event.attendees] or ['  - ""']
    content = _replace_block(content, "calendar_attendees", attendee_lines)
    content = _replace_block(content, "calendar_candidates", _calendar_candidate_lines([selected_event]))
    path.write_text(content, encoding="utf-8")


def clear_meeting_assignment(
    path: Path,
    candidates: list[CalendarEvent],
    reason: str = "external",
    title: str = "Ad Hoc Meeting",
) -> None:
    content = path.read_text(encoding="utf-8")
    content = _replace_scalar(content, "calendar_event_id", "")
    content = _replace_scalar(content, "calendar_match_confidence", reason)
    content = _replace_scalar(content, "calendar_review_queued", "false", quoted=False)
    content = _replace_scalar(content, "title", title)
    content = _replace_scalar(content, "organizer", "")
    content = _replace_scalar(content, "duration_minutes", "0", quoted=False)
    content = _replace_block(
        content,
        "calendar_candidate_event_ids",
        [f'  - "{candidate.event_id}"' for candidate in candidates] or ['  - ""'],
    )
    content = _replace_block(content, "calendar_attendees", ['  - ""'])
    content = _replace_block(content, "calendar_candidates", _calendar_candidate_lines(candidates))
    path.write_text(content, encoding="utf-8")


def _replace_scalar(content: str, key: str, value: str, quoted: bool = True) -> str:
    rendered = f'"{value}"' if quoted else value
    return re.sub(rf"^{re.escape(key)}:.*$", f"{key}: {rendered}", content, flags=re.MULTILINE)


def _replace_block(content: str, key: str, lines: list[str]) -> str:
    pattern = rf"^{re.escape(key)}:\n(?:^(?:  - |\s{{4}}).*\n?)*"
    replacement = key + ":\n" + "\n".join(lines) + "\n"
    return re.sub(pattern, replacement, content, flags=re.MULTILINE)


def _calendar_candidate_lines(candidates: list[CalendarEvent]) -> list[str]:
    candidate_lines = []
    for candidate in candidates:
        candidate_lines.extend(
            [
                f'  - id: "{candidate.event_id}"',
                f'    title: "{candidate.title}"',
                f'    conferencing: "{candidate.conferencing_type}"',
                f'    response_status: "{candidate.response_status}"',
            ]
        )
    return candidate_lines or ['  - id: ""']


def _dedupe_participants(content: str) -> str:
    match = re.search(r"^participants:\n((?:  - .*\n)+)", content, flags=re.MULTILINE)
    if not match:
        return content
    seen: set[str] = set()
    lines: list[str] = []
    for raw_line in match.group(1).splitlines():
        if raw_line not in seen:
            seen.add(raw_line)
            lines.append(raw_line)
    return _replace_block(content, "participants", lines)


def _dedupe_participants_identified(content: str) -> str:
    match = re.search(
        r"^participants_identified:\n((?:^(?:  - |\s{4}).*\n?)*)",
        content,
        flags=re.MULTILINE,
    )
    if not match:
        return content
    block = match.group(1)
    entries = _parse_participants_identified(block)
    if not entries:
        return content
    merged: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for entry in entries:
        name = entry["name"]
        if name not in merged:
            merged[name] = entry
            order.append(name)
            continue
        merged[name] = _merge_identity_entry(merged[name], entry)
    lines: list[str] = []
    for name in order:
        entry = merged[name]
        lines.append(f'  - name: "{entry["name"]}"')
        lines.append(f'    confidence: "{entry["confidence"]}"')
        if "similarity" in entry:
            lines.append(f'    similarity: {entry["similarity"]}')
        if entry.get("review_queued") == "true":
            lines.append("    review_queued: true")
    return _replace_block(content, "participants_identified", lines)


def _dedupe_participants_table(content: str) -> str:
    entries = _participants_identified_entries(content)
    pattern = r"\| Speaker \| Identity \| Confidence \|\n\|---------\|----------\|------------\|\n(?:\|.*\n)+"
    if not re.search(pattern, content):
        return content
    rows = [
        "| Speaker | Identity | Confidence |",
        "|---------|----------|------------|",
    ]
    for entry in entries:
        rows.append(f'| {entry["name"]} | {entry["name"]} | {entry["confidence"]} |')
    return re.sub(pattern, "\n".join(rows) + "\n", content, count=1)


def _parse_participants_identified(block: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in block.splitlines():
        if line.startswith("  - name: "):
            if current is not None:
                entries.append(current)
            current = {"name": line.split('"', 2)[1]}
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("confidence: "):
            current["confidence"] = stripped.split('"', 2)[1]
        elif stripped.startswith("similarity: "):
            current["similarity"] = stripped.split(": ", 1)[1]
        elif stripped == "review_queued: true":
            current["review_queued"] = "true"
    if current is not None:
        entries.append(current)
    return entries


def _participants_identified_entries(content: str) -> list[dict[str, str]]:
    match = re.search(
        r"^participants_identified:\n((?:^(?:  - |\s{4}).*\n?)*)",
        content,
        flags=re.MULTILINE,
    )
    if not match:
        return []
    return _parse_participants_identified(match.group(1))


def _merge_identity_entry(left: dict[str, str], right: dict[str, str]) -> dict[str, str]:
    merged = dict(left)
    confidence_order = {"voice_profile": 3, "mic_track": 2, "unidentified": 1}
    if confidence_order.get(right.get("confidence", ""), 0) > confidence_order.get(left.get("confidence", ""), 0):
        merged["confidence"] = right["confidence"]
    left_similarity = float(left.get("similarity", "-1"))
    right_similarity = float(right.get("similarity", "-1"))
    if right_similarity > left_similarity:
        merged["similarity"] = right["similarity"]
    if left.get("review_queued") == "true" or right.get("review_queued") == "true":
        merged["review_queued"] = "true"
    else:
        merged.pop("review_queued", None)
    return merged
