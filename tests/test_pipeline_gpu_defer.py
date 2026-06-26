"""Tests for GPU deferral in the pipeline queue."""
import asyncio
from datetime import datetime
from pathlib import Path

from mt_linux.models import MeetingInfo
from mt_linux.pipeline.job import JobStatus, PipelineJob
from mt_linux.pipeline.queue import PipelineQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore


def _make_job(session_id: str, tmp_path: Path) -> PipelineJob:
    return PipelineJob(
        session_id=session_id,
        app_audio_path=tmp_path / f"{session_id}_app.wav",
        mic_audio_path=tmp_path / f"{session_id}_mic.wav",
        meeting_info=MeetingInfo(
            app="zoom",
            pid=1,
            detection_method="import",
            start_time=datetime(2026, 6, 7, 14, 30),
        ),
    )


def test_queue_defers_when_gpu_busy(tmp_path: Path):
    """Jobs stay in queue when GPU is busy and get processed once it's free."""

    async def runner() -> None:
        store = JobSnapshotStore(tmp_path)
        queue = PipelineQueue(store=store)

        ready_state = False  # GPU starts busy
        call_count = 0
        processed_jobs: list[str] = []

        def ready_check():
            nonlocal call_count
            call_count += 1
            return ready_state

        async def processor(item: PipelineJob) -> None:
            processed_jobs.append(item.session_id)
            item.status = JobStatus.COMPLETE
            store.save(item)

        task = asyncio.create_task(
            queue.run_worker(
                processor,
                ready_check=ready_check,
                ready_poll_interval=0.05,
            )
        )

        # Enqueue jobs while GPU is busy – they should NOT be processed
        await queue.enqueue(_make_job("busy-1", tmp_path))
        await queue.enqueue(_make_job("busy-2", tmp_path))
        await asyncio.sleep(0.15)

        # Jobs should still be in queue
        assert queue._queue.qsize() == 2
        assert processed_jobs == []

        # Now make GPU available – jobs should process
        ready_state = True
        await asyncio.sleep(0.2)

        assert sorted(processed_jobs) == ["busy-1", "busy-2"]
        assert queue._queue.qsize() == 0

        # Verify ready_check was called multiple times during busy period
        assert call_count >= 2

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(runner())


def test_queue_processes_immediately_when_no_ready_check(tmp_path: Path):
    """Without ready_check, jobs process immediately (backwards compat)."""

    async def runner() -> None:
        store = JobSnapshotStore(tmp_path)
        queue = PipelineQueue(store=store)
        job = _make_job("no-check", tmp_path)
        await queue.enqueue(job)

        processed = False

        async def processor(item: PipelineJob) -> None:
            nonlocal processed
            processed = True
            item.status = JobStatus.COMPLETE
            store.save(item)
            raise asyncio.CancelledError

        task = asyncio.create_task(queue.run_worker(processor))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert processed
        assert store.load_pending() == []

    asyncio.run(runner())


def test_queue_defer_does_not_process_jobs(tmp_path: Path):
    """While deferring, no job is consumed from the queue."""

    async def runner() -> None:
        store = JobSnapshotStore(tmp_path)
        queue = PipelineQueue(store=store)
        job = _make_job("no-process", tmp_path)
        await queue.enqueue(job)

        def ready_check():
            return False  # Always busy

        async def processor(item: PipelineJob) -> None:
            raise RuntimeError("should never be called")

        task = asyncio.create_task(
            queue.run_worker(
                processor,
                ready_check=ready_check,
                ready_poll_interval=0.02,
            )
        )
        await asyncio.sleep(0.1)

        # Job should still be in queue, untouched
        assert queue._queue.qsize() == 1
        assert job.status == JobStatus.PENDING

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(runner())


def test_queue_defer_resumes_when_gpu_frees(tmp_path: Path):
    """Jobs queued during busy period process immediately once GPU frees."""

    async def runner() -> None:
        store = JobSnapshotStore(tmp_path)
        queue = PipelineQueue(store=store)

        ready_state = False
        processed: list[str] = []

        def ready_check():
            return ready_state

        async def processor(item: PipelineJob) -> None:
            processed.append(item.session_id)
            item.status = JobStatus.COMPLETE
            store.save(item)

        task = asyncio.create_task(
            queue.run_worker(
                processor,
                ready_check=ready_check,
                ready_poll_interval=0.05,
            )
        )

        # Queue up jobs while busy
        await queue.enqueue(_make_job("resume-1", tmp_path))
        await queue.enqueue(_make_job("resume-2", tmp_path))
        await asyncio.sleep(0.1)
        assert processed == []

        # GPU becomes free
        ready_state = True
        await asyncio.sleep(0.2)

        assert sorted(processed) == ["resume-1", "resume-2"]

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(runner())
