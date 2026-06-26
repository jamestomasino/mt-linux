from __future__ import annotations

from pathlib import Path

from mt_linux.config import ProtocolConfig
from mt_linux.models import MeetingInfo
from mt_linux.protocol.generator import ProtocolGenerator
from mt_linux.protocol.ollama_service import ensure_ollama_ready
from mt_linux.protocol.prompts import DEFAULT_PROMPT


class OllamaProtocolGenerator(ProtocolGenerator):
    def __init__(self, config: ProtocolConfig):
        self.config = config
        self._ready = False

    def _ensure_ready(self) -> None:
        if not self._ready:
            ensure_ollama_ready(self.config)
            self._ready = True

    def generate(self, transcript: str, meeting_info: MeetingInfo) -> str:
        self._ensure_ready()
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "httpx is not installed. Install the base dependencies to enable protocol generation."
            ) from exc
        prompt = DEFAULT_PROMPT
        if self.config.prompt_path:
            prompt = Path(self.config.prompt_path).expanduser().read_text(encoding="utf-8")

        # Inject company/personal context if configured
        context = self._load_context()

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": self._build_user_message(
                        meeting_info, transcript, context
                    ),
                },
            ],
        }
        payload["device"] = "cuda" if self.config.use_gpu else "cpu"
        response = httpx.post(self.config.endpoint, json=payload, timeout=300)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def _load_context(self) -> str:
        """Load the context file if configured."""
        ctx_path = self.config.context_file
        if not ctx_path:
            return ""
        path = Path(ctx_path).expanduser()
        if not path.exists():
            import logging

            logging.warning("Protocol context file not found: %s", path)
            return ""
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _build_user_message(
        meeting_info: MeetingInfo, transcript: str, context: str
    ) -> str:
        parts: list[str] = []
        parts.append(f"Meeting: {meeting_info.title or meeting_info.app}")
        if context:
            parts.append("")
            parts.append("## Background Context")
            parts.append(context)
        parts.append("")
        parts.append("## Transcript")
        parts.append(transcript)
        return "\n".join(parts)
