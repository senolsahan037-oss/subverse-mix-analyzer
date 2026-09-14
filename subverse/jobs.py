from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Callable
from uuid import uuid4


class JobCapacityError(RuntimeError):
    """Raised when the in-memory job queue cannot accept more work."""


@dataclass
class AnalysisJob:
    id: str
    status: str = "queued"
    progress: int = 0
    result: dict[str, object] | None = None
    error: str | None = None
    updated_at: float = field(default_factory=monotonic, repr=False)


class AnalysisJobStore:
    def __init__(
        self,
        workers: int,
        ttl_seconds: int = 60 * 60,
        max_records: int = 1000,
    ) -> None:
        self._jobs: dict[str, AnalysisJob] = {}
        self._lock = Lock()
        self._ttl_seconds = ttl_seconds
        self._max_records = max_records
        self._executor = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="audio-analysis",
        )

    def _purge_locked(self, reserve_slot: bool = False) -> None:
        now = monotonic()
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status in {"completed", "failed"}
            and now - job.updated_at >= self._ttl_seconds
        ]
        for job_id in expired:
            del self._jobs[job_id]

        overflow = (
            len(self._jobs)
            - self._max_records
            + (1 if reserve_slot else 0)
        )
        if overflow <= 0:
            return
        terminal = sorted(
            (
                job
                for job in self._jobs.values()
                if job.status in {"completed", "failed"}
            ),
            key=lambda job: job.updated_at,
        )
        for job in terminal[:overflow]:
            del self._jobs[job.id]

    def submit(
        self,
        path: Path,
        analyze: Callable[[Path], dict[str, object]],
        finalize: Callable[[dict[str, object]], dict[str, object]],
    ) -> AnalysisJob:
        job = AnalysisJob(id=uuid4().hex)
        with self._lock:
            self._purge_locked(reserve_slot=True)
            if len(self._jobs) >= self._max_records:
                raise JobCapacityError("Analysis job capacity has been reached.")
            self._jobs[job.id] = job

        def run() -> None:
            with self._lock:
                job.status, job.progress, job.updated_at = "running", 10, monotonic()
            try:
                result = finalize(analyze(path))
                with self._lock:
                    job.result, job.status, job.progress, job.updated_at = (
                        result,
                        "completed",
                        100,
                        monotonic(),
                    )
            except Exception:
                with self._lock:
                    job.error, job.status, job.progress, job.updated_at = (
                        "Analysis could not be completed.",
                        "failed",
                        100,
                        monotonic(),
                    )
            finally:
                path.unlink(missing_ok=True)

        try:
            self._executor.submit(run)
        except RuntimeError as exc:
            with self._lock:
                self._jobs.pop(job.id, None)
            raise JobCapacityError(
                "Analysis job executor is unavailable."
            ) from exc
        return job

    def get(self, job_id: str) -> AnalysisJob | None:
        with self._lock:
            self._purge_locked()
            job = self._jobs.get(job_id)
            return None if job is None else replace(job)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)
