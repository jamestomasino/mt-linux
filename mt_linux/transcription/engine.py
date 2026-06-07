from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from mt_linux.models import TranscriptSegment


class TranscribingEngine(ABC):
    @abstractmethod
    def transcribe(self, audio_path: Path, language: str | None = None) -> list[TranscriptSegment]:
        raise NotImplementedError
