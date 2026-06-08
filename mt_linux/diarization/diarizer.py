from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DiarizationSegment:
    start: float
    end: float
    speaker: str


class PyannoteDiarizer:
    def __init__(self, hf_token: str, num_speakers: int | None = None):
        try:
            import torch
            from pyannote.audio import Pipeline as DiarizationPipeline
        except ImportError as exc:
            raise RuntimeError(
                "pyannote.audio is not installed. Install the diarization extras to enable diarization."
            ) from exc
        self.pipeline = DiarizationPipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=hf_token,
        )
        self.pipeline.to(torch.device("cpu"))
        self.num_speakers = num_speakers

    def diarize(self, audio_path: Path) -> list[DiarizationSegment]:
        kwargs = {}
        if self.num_speakers:
            kwargs["num_speakers"] = self.num_speakers
        diarization = self.pipeline(str(audio_path), **kwargs)
        annotation = getattr(diarization, "exclusive_speaker_diarization", None)
        if annotation is None:
            annotation = getattr(diarization, "speaker_diarization", diarization)
        return [
            DiarizationSegment(start=turn.start, end=turn.end, speaker=speaker)
            for turn, _, speaker in annotation.itertracks(yield_label=True)
        ]
