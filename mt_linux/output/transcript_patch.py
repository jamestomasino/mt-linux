from __future__ import annotations

from pathlib import Path
import re

from mt_linux.models import CalendarEvent


def replace_speaker_label(path: Path, speaker_label: str, speaker_name: str) -> None:
    content = path.read_text(encoding="utf-8")
    wikified = f"[[{speaker_name}]]"
    content = content.replace(speaker_label, wikified)
    content = re.sub(
        rf'(name:\s*"{re.escape(wikified)}"\n\s*confidence:\s*)"unidentified"',
        r'\1"voice_profile"',
        content,
    )
    content = content.replace("\n    review_queued: true", "")
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
    content = _replace_block(
        content,
        "calendar_candidate_event_ids",
        [f'  - "{candidate.event_id}"' for candidate in candidates] or ['  - ""'],
    )
    attendee_lines = [f'  - "{attendee.display()}"' for attendee in selected_event.attendees] or ['  - ""']
    content = _replace_block(content, "calendar_attendees", attendee_lines)
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
    content = _replace_block(content, "calendar_candidates", candidate_lines or ['  - id: ""'])
    path.write_text(content, encoding="utf-8")


def clear_meeting_assignment(
    path: Path,
    candidates: list[CalendarEvent],
    reason: str = "external",
) -> None:
    content = path.read_text(encoding="utf-8")
    content = _replace_scalar(content, "calendar_event_id", "")
    content = _replace_scalar(content, "calendar_match_confidence", reason)
    content = _replace_scalar(content, "calendar_review_queued", "false", quoted=False)
    content = _replace_scalar(content, "title", "Ad Hoc Meeting")
    content = _replace_scalar(content, "organizer", "")
    content = _replace_scalar(content, "duration_minutes", "0", quoted=False)
    content = _replace_block(
        content,
        "calendar_candidate_event_ids",
        [f'  - "{candidate.event_id}"' for candidate in candidates] or ['  - ""'],
    )
    content = _replace_block(content, "calendar_attendees", ['  - ""'])
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
    content = _replace_block(content, "calendar_candidates", candidate_lines or ['  - id: ""'])
    path.write_text(content, encoding="utf-8")


def _replace_scalar(content: str, key: str, value: str, quoted: bool = True) -> str:
    rendered = f'"{value}"' if quoted else value
    return re.sub(rf"^{re.escape(key)}:.*$", f"{key}: {rendered}", content, flags=re.MULTILINE)


def _replace_block(content: str, key: str, lines: list[str]) -> str:
    pattern = rf"^{re.escape(key)}:\n(?:^(?:  - |\s{{4}}).*\n?)*"
    replacement = key + ":\n" + "\n".join(lines) + "\n"
    return re.sub(pattern, replacement, content, flags=re.MULTILINE)
