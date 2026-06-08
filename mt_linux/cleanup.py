from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mt_linux.paths import DATA_DIR, REVIEW_SAMPLES_DIR
from mt_linux.pipeline.review_queue import ReviewQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore


@dataclass
class CleanupResult:
    removed_paths: list[Path]
    removed_job_snapshots: list[Path]


def cleanup_runtime_artifacts(
    *,
    dry_run: bool = False,
    include_job_history: bool = False,
    store: JobSnapshotStore | None = None,
    review_queue: ReviewQueue | None = None,
) -> CleanupResult:
    store = store or JobSnapshotStore()
    review_queue = review_queue or ReviewQueue()

    removed_paths: list[Path] = []
    removed_job_snapshots: list[Path] = []

    if include_job_history:
        for job in store.load_all():
            if job.status.value not in {"complete", "failed"}:
                continue
            path = store.path_for(job.session_id)
            if path.exists():
                removed_job_snapshots.append(path)
                if not dry_run:
                    path.unlink()

    referenced_audio = _referenced_audio_paths(store)
    for path in sorted((DATA_DIR / "audio").glob("*.wav")):
        if path in referenced_audio:
            continue
        removed_paths.append(path)
        if not dry_run:
            path.unlink()

    referenced_samples = {entry.sample_path.resolve() for entry in review_queue.load()}
    for path in sorted(REVIEW_SAMPLES_DIR.glob("*.wav")):
        if path.resolve() in referenced_samples:
            continue
        removed_paths.append(path)
        if not dry_run:
            path.unlink()

    return CleanupResult(
        removed_paths=removed_paths,
        removed_job_snapshots=removed_job_snapshots,
    )


def _referenced_audio_paths(store: JobSnapshotStore) -> set[Path]:
    referenced: set[Path] = set()
    for job in store.load_all():
        referenced.add(job.app_audio_path.resolve())
        referenced.add(job.mic_audio_path.resolve())
        if job.imported_audio_path is not None:
            referenced.add(job.imported_audio_path.resolve())
        mixed = job.app_audio_path.with_name(f"{job.session_id}_mix.wav")
        referenced.add(mixed.resolve())
    return referenced
