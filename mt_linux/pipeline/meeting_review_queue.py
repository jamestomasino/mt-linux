from __future__ import annotations

import json
from pathlib import Path

from mt_linux.models import MeetingReviewEntry
from mt_linux.paths import MEETING_REVIEW_QUEUE_FILE, ensure_directories


class MeetingReviewQueue:
    def __init__(self, path: Path = MEETING_REVIEW_QUEUE_FILE):
        self.path = path
        ensure_directories()

    def load(self) -> list[MeetingReviewEntry]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [MeetingReviewEntry.from_dict(item) for item in raw]

    def save(self, entries: list[MeetingReviewEntry]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([entry.to_dict() for entry in entries], indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, entry: MeetingReviewEntry) -> None:
        entries = [item for item in self.load() if item.session_id != entry.session_id]
        entries.append(entry)
        self.save(entries)

    def remove(self, session_id: str) -> None:
        entries = [entry for entry in self.load() if entry.session_id != session_id]
        self.save(entries)
