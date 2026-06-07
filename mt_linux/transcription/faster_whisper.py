from __future__ import annotations

from pathlib import Path

from mt_linux.config import TranscriptionConfig
from mt_linux.models import TranscriptSegment
from mt_linux.transcription.engine import TranscribingEngine


class FasterWhisperEngine(TranscribingEngine):
    def __init__(self, config: TranscriptionConfig):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. Install the transcription extras to enable ASR."
            ) from exc
        self.model = WhisperModel(
            config.model,
            device=config.device,
            compute_type=config.compute_type,
        )

    def transcribe(self, audio_path: Path, language: str | None = None) -> list[TranscriptSegment]:
        segments, _info = self.model.transcribe(
            str(audio_path),
            language=language,
            word_timestamps=True,
        )
        return [
            TranscriptSegment(
                start=float(segment.start),
                end=float(segment.end),
                text=segment.text.strip(),
            )
            for segment in segments
        ]
