import asyncio
from datetime import datetime
from pathlib import Path

from mt_linux.models import MeetingInfo
from mt_linux.pipeline.job import JobStatus, PipelineJob
from mt_linux.pipeline.queue import PipelineQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore


def test_pipeline_queue_persists_and_processes_job(tmp_path: Path):
    async def runner() -> None:
        store = JobSnapshotStore(tmp_path)
        queue = PipelineQueue(store=store)
        job = PipelineJob(
            session_id="session-1",
            app_audio_path=tmp_path / "app.wav",
            mic_audio_path=tmp_path / "mic.wav",
            meeting_info=MeetingInfo(
                app="zoom",
                pid=1,
                detection_method="import",
                start_time=datetime(2026, 6, 7, 14, 30),
            ),
        )
        await queue.enqueue(job)

        async def processor(item: PipelineJob) -> None:
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

        restored = store.load_pending()
        assert restored == []

    asyncio.run(runner())
