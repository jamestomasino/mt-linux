from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from mt_linux.pipeline.job import PipelineJob, JobStatus
from mt_linux.pipeline.snapshot import JobSnapshotStore


PipelineProcessor = Callable[[PipelineJob], Awaitable[None]]
FailureCallback = Callable[[PipelineJob, Exception], None]
ReadyCheck = Callable[[], bool]


class PipelineQueue:
    def __init__(self, store: JobSnapshotStore | None = None):
        self._queue: asyncio.Queue[PipelineJob] = asyncio.Queue()
        self._active_job: PipelineJob | None = None
        self._queued_session_ids: list[str] = []
        self.store = store or JobSnapshotStore()

    @property
    def active_job(self) -> PipelineJob | None:
        return self._active_job

    async def enqueue(self, job: PipelineJob) -> None:
        await self._queue.put(job)
        self._queued_session_ids.append(job.session_id)
        self.store.save(job)

    async def restore(self) -> None:
        for job in self.store.load_pending():
            await self._queue.put(job)
            self._queued_session_ids.append(job.session_id)

    def snapshot(self) -> dict[str, object]:
        return {
            "active_job": self._active_job.session_id if self._active_job else None,
            "queue_depth": self._queue.qsize(),
            "queued_jobs": list(self._queued_session_ids),
        }

    async def run_worker(
        self,
        processor: PipelineProcessor,
        on_failure: FailureCallback | None = None,
        *,
        ready_check: ReadyCheck | None = None,
        ready_poll_interval: float = 30.0,
    ) -> None:
        last_defer_log: float = 0.0
        while True:
            # Check GPU readiness BEFORE pulling a job so we don't start
            # processing when the GPU is consumed by another process.
            if ready_check is not None and not ready_check():
                # Yield to the event loop so other tasks can make progress,
                # then immediately retry.  Log at most once per poll interval.
                now = asyncio.get_event_loop().time()
                if now - last_defer_log >= ready_poll_interval:
                    logging.info("GPU busy – deferring queue processing")
                    last_defer_log = now
                await asyncio.sleep(0.2)
                continue

            job = await self._queue.get()
            self._discard_queued_session_id(job.session_id)
            self._active_job = job
            self.store.save(job)
            try:
                await processor(job)
                if job.status not in {JobStatus.COMPLETE, JobStatus.FAILED}:
                    await self._queue.put(job)
                    self._queued_session_ids.append(job.session_id)
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = str(exc)
                self.store.save(job)
                if on_failure is not None:
                    on_failure(job, exc)
            finally:
                self._active_job = None
                self._queue.task_done()

    def _discard_queued_session_id(self, session_id: str) -> None:
        try:
            self._queued_session_ids.remove(session_id)
        except ValueError:
            return
