from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from mt_linux.transcription.runtime import resolve_device


# Singleton VoiceEncoder — loaded once, reused across all calls.
_ENCODER = None


def _get_encoder():
    global _ENCODER
    if _ENCODER is None:
        from resemblyzer import VoiceEncoder
        _ENCODER = VoiceEncoder(device=resolve_device("auto"))
    return _ENCODER


class SpeakerMatcher:
    def __init__(self, db_path: Path, similarity_threshold: float = 0.75):
        self.db_path = db_path
        self.similarity_threshold = similarity_threshold
        self.db = self._load()

    def match_embedding(self, embedding: np.ndarray) -> tuple[str, float] | None:
        best_name = None
        best_similarity = 0.0
        for name, profile in self.db.items():
            centroid = np.array(profile["centroid"], dtype=float)
            similarity = float(np.dot(embedding, centroid))
            if similarity > best_similarity:
                best_name = name
                best_similarity = similarity
        if best_name and best_similarity >= self.similarity_threshold:
            return best_name, best_similarity
        return None

    def update_profile(self, name: str, embedding: np.ndarray) -> None:
        profile = self.db.setdefault(name, {"embeddings": [], "centroid": None})
        profile["embeddings"] = (profile["embeddings"] + [embedding.tolist()])[-20:]
        centroid = np.mean(np.array(profile["embeddings"], dtype=float), axis=0)
        norm = np.linalg.norm(centroid)
        if norm:
            centroid = centroid / norm
        profile["centroid"] = centroid.tolist()
        self._save()

    def embed_wav(self, wav_path: Path) -> np.ndarray:
        try:
            from resemblyzer import preprocess_wav
        except ImportError as exc:
            raise RuntimeError(
                "resemblyzer is not installed. Install the diarization extras to enable speaker enrollment."
            ) from exc
        encoder = _get_encoder()
        wav = preprocess_wav(str(wav_path))
        embedding = encoder.embed_utterance(wav)
        norm = np.linalg.norm(embedding)
        return embedding / norm if norm else embedding

    def embed_multiple(self, wav_paths: list[Path]) -> np.ndarray | None:
        """Average embeddings from multiple clips for a more stable speaker profile."""
        embeddings: list[np.ndarray] = []
        for path in wav_paths:
            try:
                emb = self.embed_wav(path)
                embeddings.append(emb)
            except Exception:
                continue
        if not embeddings:
            return None
        averaged = np.mean(embeddings, axis=0)
        norm = np.linalg.norm(averaged)
        return averaged / norm if norm else averaged

    def _load(self) -> dict:
        if not self.db_path.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            return {}
        return json.loads(self.db_path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.db_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.db, indent=2), encoding="utf-8")
        tmp.replace(self.db_path)
