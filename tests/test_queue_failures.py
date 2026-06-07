import asyncio
from datetime import UTC, datetime
from pathlib import Path

from mt_linux.models import MeetingInfo
from mt_linux.pipeline.job import JobStatus, PipelineJob
from mt_linux.pipeline.queue import PipelineQueue
from mt_linux.pipeline.snapshot import JobSnapshotStore


def test_pipeline_queue_marks_failure_and_invokes_callback(tmp_path: Path):
    async def runner():
        store = JobSnapshotStore(tmp_path / "jobs")
        queue = PipelineQueue(store=store)
        job = PipelineJob(
            session_id="session-1",
            app_audio_path=tmp_path / "app.wav",
            mic_audio_path=tmp_path / "mic.wav",
            meeting_info=MeetingInfo(
                app="zoom",
                pid=1,
                detection_method="import",
                start_time=datetime(2026, 6, 7, 14, 30, tzinfo=UTC),
            ),
        )
        await queue.enqueue(job)
        failures = []

        async def processor(item: PipelineJob) -> None:
            raise RuntimeError("boom")

        task = asyncio.create_task(
            queue.run_worker(processor, on_failure=lambda item, exc: failures.append((item.session_id, str(exc))))
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert failures == [("session-1", "boom")]
        snapshot = store.path_for("session-1").read_text(encoding="utf-8")
        assert '"status": "failed"' in snapshot

    asyncio.run(runner())
