from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from mt_linux.pipeline.job import PipelineJob, JobStatus
from mt_linux.pipeline.snapshot import JobSnapshotStore


PipelineProcessor = Callable[[PipelineJob], Awaitable[None]]
FailureCallback = Callable[[PipelineJob, Exception], None]


class PipelineQueue:
    def __init__(self, store: JobSnapshotStore | None = None):
        self._queue: asyncio.Queue[PipelineJob] = asyncio.Queue()
        self._active_job: PipelineJob | None = None
        self.store = store or JobSnapshotStore()

    @property
    def active_job(self) -> PipelineJob | None:
        return self._active_job

    async def enqueue(self, job: PipelineJob) -> None:
        await self._queue.put(job)
        self.store.save(job)

    async def restore(self) -> None:
        for job in self.store.load_pending():
            await self._queue.put(job)

    def snapshot(self) -> dict[str, object]:
        return {
            "active_job": self._active_job.session_id if self._active_job else None,
            "queue_depth": self._queue.qsize(),
        }

    async def run_worker(
        self,
        processor: PipelineProcessor,
        on_failure: FailureCallback | None = None,
    ) -> None:
        while True:
            job = await self._queue.get()
            self._active_job = job
            self.store.save(job)
            try:
                await processor(job)
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = str(exc)
                self.store.save(job)
                if on_failure is not None:
                    on_failure(job, exc)
            finally:
                self._active_job = None
                self._queue.task_done()
