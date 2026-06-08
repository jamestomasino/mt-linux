from __future__ import annotations

import json
from pathlib import Path

from mt_linux.paths import JOBS_DIR, ensure_directories
from mt_linux.pipeline.job import PipelineJob, JobStatus


class JobSnapshotStore:
    def __init__(self, jobs_dir: Path = JOBS_DIR):
        self.jobs_dir = jobs_dir
        ensure_directories()

    def path_for(self, session_id: str) -> Path:
        return self.jobs_dir / f"{session_id}.json"

    def save(self, job: PipelineJob) -> Path:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(job.session_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)
        return path

    def load_all(self) -> list[PipelineJob]:
        jobs: list[PipelineJob] = []
        for path in sorted(self.jobs_dir.glob("*.json")):
            jobs.append(PipelineJob.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return jobs

    def load_one(self, session_id: str) -> PipelineJob | None:
        path = self.path_for(session_id)
        if not path.exists():
            return None
        return PipelineJob.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def remove(self, session_id: str) -> bool:
        path = self.path_for(session_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def load_pending(self) -> list[PipelineJob]:
        jobs: list[PipelineJob] = []
        for job in self.load_all():
            if job.status not in {JobStatus.COMPLETE, JobStatus.FAILED}:
                jobs.append(job)
        return jobs
