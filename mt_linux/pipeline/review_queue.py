from __future__ import annotations

import json
from pathlib import Path

from mt_linux.models import ReviewEntry
from mt_linux.paths import REVIEW_QUEUE_FILE, ensure_directories


class ReviewQueue:
    def __init__(self, path: Path = REVIEW_QUEUE_FILE):
        self.path = path
        ensure_directories()

    def load(self) -> list[ReviewEntry]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [ReviewEntry.from_dict(item) for item in raw]

    def save(self, entries: list[ReviewEntry]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps([entry.to_dict() for entry in entries], indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def add(self, entry: ReviewEntry) -> None:
        entries = self.load()
        entries = [
            item
            for item in entries
            if not (item.session_id == entry.session_id and item.speaker_label == entry.speaker_label)
        ]
        entries.append(entry)
        self.save(entries)

    def remove(self, session_id: str, speaker_label: str) -> None:
        entries = [
            entry
            for entry in self.load()
            if not (entry.session_id == session_id and entry.speaker_label == speaker_label)
        ]
        self.save(entries)
