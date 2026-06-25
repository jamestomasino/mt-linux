from __future__ import annotations

from pathlib import Path

from mt_linux.config import TranscriptionConfig
from mt_linux.models import TranscriptSegment
from mt_linux.transcription.engine import TranscribingEngine
from mt_linux.transcription.runtime import resolve_device


class FasterWhisperEngine(TranscribingEngine):
    def __init__(self, config: TranscriptionConfig):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. Install the transcription extras to enable ASR."
            ) from exc
        device = resolve_device(config.device)
        self.model = WhisperModel(
            config.model,
            device=device,
            compute_type=config.compute_type,
        )

    def transcribe(self, audio_path: Path, language: str | None = None) -> list[TranscriptSegment]:
        vad_parameters = (
            {"min_silence_duration_ms": 500}
            if self.config.chunking_strategy == "vad"
            else None
        )
        segments, _info = self.model.transcribe(
            str(audio_path),
            language=language,
            beam_size=self.config.beam_size,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=vad_parameters,
            condition_on_previous_text=False,
        )
        return [
            TranscriptSegment(
                start=float(segment.start),
                end=float(segment.end),
                text=segment.text.strip(),
                confidence=float(segment.avg_logprob) if getattr(segment, "avg_logprob", None) is not None else None,
                no_speech_prob=float(segment.no_speech_prob)
                if getattr(segment, "no_speech_prob", None) is not None
                else None,
            )
            for segment in segments
        ]
