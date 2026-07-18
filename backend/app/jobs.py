from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Callable
from uuid import uuid4


@dataclass
class AnalysisJob:
    id: str
    status: str = "queued"
    progress: int = 0
    result: dict[str, object] | None = None
    error: str | None = None


class AnalysisJobStore:
    def __init__(self, workers: int) -> None:
        self._jobs: dict[str, AnalysisJob] = {}
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="audio-analysis")

    def submit(
        self,
        path: Path,
        analyze: Callable[[Path], dict[str, object]],
        finalize: Callable[[dict[str, object]], dict[str, object]],
    ) -> AnalysisJob:
        job = AnalysisJob(id=uuid4().hex)
        with self._lock:
            self._jobs[job.id] = job

        def run() -> None:
            with self._lock:
                job.status, job.progress = "running", 10
            try:
                result = finalize(analyze(path))
                with self._lock:
                    job.result, job.status, job.progress = result, "completed", 100
            except Exception:
                with self._lock:
                    job.error, job.status, job.progress = "Analysis could not be completed.", "failed", 100
            finally:
                path.unlink(missing_ok=True)

        self._executor.submit(run)
        return job

    def get(self, job_id: str) -> AnalysisJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
