from __future__ import annotations

from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest

from subverse.jobs import AnalysisJobStore, JobCapacityError


def _complete_job(store: AnalysisJobStore, path: Path) -> str:
    completed = Event()
    path.write_bytes(b"audio")
    job = store.submit(
        path,
        lambda _: {"duration_seconds": 1.0},
        lambda result: (completed.set(), result)[1],
    )
    assert completed.wait(timeout=1)
    for _ in range(100):
        current = store.get(job.id)
        if current is not None and current.status == "completed":
            return job.id
        sleep(0.001)
    raise AssertionError("Job did not complete.")


def test_completed_jobs_expire_and_release_capacity(tmp_path: Path) -> None:
    store = AnalysisJobStore(workers=1, ttl_seconds=1, max_records=1)
    try:
        job_id = _complete_job(store, tmp_path / "first.wav")
        with store._lock:
            store._jobs[job_id].updated_at = monotonic() - 2

        assert store.get(job_id) is None
        second_id = _complete_job(store, tmp_path / "second.wav")
        assert store.get(second_id) is not None
    finally:
        store.shutdown()


def test_active_jobs_respect_capacity_limit(tmp_path: Path) -> None:
    store = AnalysisJobStore(workers=1, ttl_seconds=60, max_records=1)
    blocker = tmp_path / "blocked.wav"
    blocker.write_bytes(b"audio")
    started = Event()
    release = Event()

    def blocked_analysis(_: Path) -> dict[str, object]:
        started.set()
        assert release.wait(timeout=1)
        return {"duration_seconds": 1.0}

    try:
        store.submit(
            blocker,
            blocked_analysis,
            lambda result: result,
        )
        assert started.wait(timeout=1)

        with pytest.raises(JobCapacityError):
            store.submit(
                tmp_path / "second.wav",
                lambda _: {},
                lambda result: result,
            )
    finally:
        release.set()
        store.shutdown()
