from __future__ import annotations

from pathlib import Path

from mt_linux.models import MeetingReviewEntry, ReviewEntry
from mt_linux.pipeline.job import JobStatus, PipelineJob
from mt_linux.pipeline.meeting_review_queue import MeetingReviewQueue
from mt_linux.pipeline.review_queue import ReviewQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore


def remove_job(
    session_id: str,
    *,
    delete_audio: bool = False,
    review_queue: ReviewQueue | None = None,
    meeting_review_queue: MeetingReviewQueue | None = None,
    store: JobSnapshotStore | None = None,
) -> tuple[bool, list[Path]]:
    store = store or JobSnapshotStore()
    review_queue = review_queue or ReviewQueue()
    meeting_review_queue = meeting_review_queue or MeetingReviewQueue()
    job = store.load_one(session_id)
    if job is None:
        return False, []
    deleted_paths: list[Path] = []
    _remove_review_entries(session_id, review_queue, deleted_paths)
    _remove_meeting_review_entries(session_id, meeting_review_queue)
    if delete_audio:
        for path in _job_audio_paths(job):
            if path.exists():
                path.unlink()
                deleted_paths.append(path)
    store.remove(session_id)
    return True, deleted_paths


def retry_job(
    session_id: str,
    *,
    review_queue: ReviewQueue | None = None,
    meeting_review_queue: MeetingReviewQueue | None = None,
    store: JobSnapshotStore | None = None,
) -> tuple[bool, str]:
    store = store or JobSnapshotStore()
    review_queue = review_queue or ReviewQueue()
    meeting_review_queue = meeting_review_queue or MeetingReviewQueue()
    job = store.load_one(session_id)
    if job is None:
        return False, "not_found"
    if job.status != JobStatus.FAILED:
        return False, "not_failed"
    deleted_paths: list[Path] = []
    _remove_review_entries(session_id, review_queue, deleted_paths)
    _remove_meeting_review_entries(session_id, meeting_review_queue)
    job.error = None
    job.set_status(JobStatus.PENDING, "Retry requested")
    store.save(job)
    return True, "retried"


def _remove_review_entries(session_id: str, queue: ReviewQueue, deleted_paths: list[Path]) -> None:
    remaining: list[ReviewEntry] = []
    for entry in queue.load():
        if entry.session_id != session_id:
            remaining.append(entry)
            continue
        if entry.sample_path.exists():
            entry.sample_path.unlink()
            deleted_paths.append(entry.sample_path)
    queue.save(remaining)


def _remove_meeting_review_entries(session_id: str, queue: MeetingReviewQueue) -> None:
    remaining: list[MeetingReviewEntry] = [
        entry for entry in queue.load() if entry.session_id != session_id
    ]
    queue.save(remaining)


def _job_audio_paths(job: PipelineJob) -> list[Path]:
    paths = [job.app_audio_path, job.mic_audio_path]
    if job.imported_audio_path is not None:
        paths.append(job.imported_audio_path)
    mixed = job.app_audio_path.with_name(f"{job.session_id}_mix.wav")
    if mixed not in paths:
        paths.append(mixed)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser()
        if resolved in seen:
            continue
        deduped.append(path)
        seen.add(resolved)
    return deduped
