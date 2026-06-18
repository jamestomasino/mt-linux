from __future__ import annotations

from pathlib import Path

from mt_linux.config import ProtocolConfig
from mt_linux.models import MeetingInfo
from mt_linux.protocol.generator import ProtocolGenerator
from mt_linux.protocol.prompts import DEFAULT_PROMPT


class OllamaProtocolGenerator(ProtocolGenerator):
    def __init__(self, config: ProtocolConfig):
        self.config = config

    def generate(self, transcript: str, meeting_info: MeetingInfo) -> str:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "httpx is not installed. Install the base dependencies to enable protocol generation."
            ) from exc
        prompt = DEFAULT_PROMPT
        if self.config.prompt_path:
            prompt = Path(self.config.prompt_path).expanduser().read_text(encoding="utf-8")
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": f"Meeting: {meeting_info.title or meeting_info.app}\n\n{transcript}",
                },
            ],
        }
        if self.config.use_gpu:
            payload["device"] = "cuda"
        else:
            payload["device"] = "cpu"
        response = httpx.post(self.config.endpoint, json=payload, timeout=300)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
