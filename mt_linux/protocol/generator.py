from __future__ import annotations

from abc import ABC, abstractmethod

from mt_linux.models import MeetingInfo


class ProtocolGenerator(ABC):
    @abstractmethod
    def generate(self, transcript: str, meeting_info: MeetingInfo) -> str:
        raise NotImplementedError
