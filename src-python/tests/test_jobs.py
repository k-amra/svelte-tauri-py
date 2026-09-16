"""Tests for JobManager retention: history cap, abandonment, release."""

import threading
import time

from app.core import jobs as jobs_module
from app.core.jobs import Job, JobManager


def _wait_until(manager: JobManager, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    snap = manager.snapshot(job_id)
    while snap is not None and snap["status"] == "running" and time.time() < deadline:
        time.sleep(0.01)
        snap = manager.snapshot(job_id)
    assert snap is not None
    return snap


def _instant(params, progress):
    return {"ok": True}


def test_max_job_age_leaves_headroom_above_client_timeout():
    # Must stay strictly above both the client's waitJob default (30 min)
    # and the worst-case real fetch — but only the lower bound is pinned,
    # so raising it further never goes red.
    assert jobs_module.MAX_JOB_AGE_S >= 2 * 60 * 60


def test_history_cap_evicts_oldest_with_flag():
    manager = JobManager()
    manager._max_history = 3
    submitted = [manager.submit("t", _instant, None) for _ in range(5)]
    # Wait on the objects, not snapshots: completed jobs may already be
    # evicted (popped) from the dict while later siblings still run.
    deadline = time.time() + 10
    while time.time() < deadline and any(j.status == "running" for j in submitted):
        time.sleep(0.01)
    assert all(j.status == "done" for j in submitted)
    assert len(manager._jobs) == 3
    # The two oldest are gone from the dict but flagged on the orphaned objects.
    for job in submitted[:2]:
        assert job.id not in manager._jobs
        assert job.evicted is True
        assert job.result is None
        assert len(job.events) == 0
    for job in submitted[2:]:
        assert job.evicted is False


def test_eviction_runs_at_submit_time():
    manager = JobManager()
    manager._max_history = 2
    for i in range(3):
        job = Job(id=f"old-{i}", script="t", status="done", result={"ok": True})
        job.push(100.0, "done")
        manager._jobs[job.id] = job
    gate = threading.Event()

    def blocking(params, progress):
        gate.wait(10)
        return {"ok": True}

    try:
        manager.submit("t", blocking, None)
        # Trimmed at submit, before the new job completes.
        assert len(manager._jobs) <= 2
        assert "old-0" not in manager._jobs
        assert "old-1" not in manager._jobs
    finally:
        gate.set()


def test_abandoned_running_jobs_age_out_without_resurrection():
    manager = JobManager()
    gate = threading.Event()
    exited = threading.Event()

    def blocking(params, progress):
        try:
            gate.wait(10)
            progress(50.0, "half")  # evicted by now -> raises InterruptedError
            return {"ok": True}
        finally:
            exited.set()

    stuck = manager.submit("t", blocking, None)
    # Backdate past the max age, then trigger eviction via a fresh submit.
    stuck.created_at -= jobs_module.MAX_JOB_AGE_S + 1
    done = manager.submit("t", _instant, None)
    try:
        assert _wait_until(manager, done.id)["status"] == "done"
        gate.set()
        # Bounded wait for the worker thread itself (not a fixed sleep): a
        # worker that ignored eviction would flip status to "done" below.
        assert exited.wait(5), "worker thread did not observe eviction and exit"
        assert stuck.id not in manager._jobs
        assert stuck.evicted is True
        assert stuck.status == "error"
        assert stuck.error == "job evicted: exceeded max age"
        assert stuck.result is None
        assert done.evicted is False
    finally:
        gate.set()


def test_release_drops_payload_keeps_status():
    manager = JobManager()

    def noisy(params, progress):
        for i in range(5):
            progress(float(i), f"msg {i}")
        return {"ok": True}

    job = manager.submit("t", noisy, None)
    snap = _wait_until(manager, job.id)
    assert snap["status"] == "done"
    assert snap["result"] == {"ok": True}
    manager.release(job.id)
    snap = manager.snapshot(job.id)
    assert snap is not None
    assert snap["status"] == "done"
    assert snap["result"] is None
    # Terminal event kept for late SSE subscribers.
    assert len(manager._jobs[job.id].events) == 1
    assert manager._jobs[job.id].events[0]["progress"] == 100.0
    # Idempotent + unknown ids are a no-op.
    manager.release(job.id)
    manager.release("nope")


def test_release_leaves_running_job_alone():
    manager = JobManager()
    gate = threading.Event()

    def blocking(params, progress):
        gate.wait(10)
        return {"ok": True}

    try:
        job = manager.submit("t", blocking, None)
        manager.release(job.id)
        snap = manager.snapshot(job.id)
        assert snap is not None
        assert snap["status"] == "running"
        gate.set()
        assert _wait_until(manager, job.id)["status"] == "done"
    finally:
        gate.set()
