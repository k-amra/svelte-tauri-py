"""Background job manager for long-running scripts (>2s).

Scripts report progress via a `progress(pct, msg)` callback.
Jobs run in a daemon thread so sync script code never blocks the
event loop — and so TestClient (sync portal) tests work as well.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

MAX_EVENTS_PER_JOB = 500  # ring buffer; enough for the SSE UI to tail
# Retained completed jobs. A single chat_stats result can be tens of MB
# (all_urls + per_channel), so 100 results could pin gigabytes of RAM.
# 20 keeps the retained set bounded at a few hundred MB worst case.
MAX_JOB_HISTORY = 20
# Abandoned running jobs (blocked thread, hung I/O) used to accumulate
# forever; evict them after this age.
# Worst case is the "All" preset (3650 days). A cold-cache decade fetch
# can take 45–90 minutes; must stay comfortably above the client's
# waitJob timeout (30 min) and the realistic worst-case fetch.
MAX_JOB_AGE_S = 4 * 60 * 60  # 4 hours


@dataclass
class Job:
    id: str
    script: str
    status: str = "running"  # running | done | error
    progress: float = 0.0
    message: str = ""
    result: Any | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    events: deque[dict] = field(default_factory=lambda: deque(maxlen=MAX_EVENTS_PER_JOB))
    # Monotonic sequence assigned to each pushed event. Survives ring-buffer
    # drops: the client cursor is compared against seq, not list index.
    next_seq: int = 0
    evicted: bool = False

    def push(self, pct: float, msg: str = "") -> None:
        self.progress = pct
        self.message = msg
        self.events.append({
            "seq": self.next_seq,
            "progress": pct,
            "message": msg,
            "t": time.time(),
        })
        self.next_seq += 1

    def to_dict(self) -> dict:
        # NOTE: events are intentionally excluded from the snapshot; the
        # SSE endpoint is the only consumer of the event stream.
        return {
            "job_id": self.id,
            "script": self.script,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
        }


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_history = MAX_JOB_HISTORY
        self._shutdown = threading.Event()

    def request_shutdown(self) -> None:
        """Signal running jobs to abort at their next progress() checkpoint."""
        self._shutdown.set()

    def submit(self, script: str, func: Callable, params: Any) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], script=script)
        with self._lock:
            self._jobs[job.id] = job
            # Run eviction at submit time too: without this, a steady stream
            # of new jobs would only trim on completion, and abandoned
            # running jobs would never age out.
            self._evict_old_jobs()
        t = threading.Thread(target=self._run, args=(job, func, params), daemon=True)
        t.start()
        return job

    def _run(self, job: Job, func: Callable, params: Any) -> None:
        def progress(pct: float, msg: str = "") -> None:
            if self._shutdown.is_set():
                raise InterruptedError("server shutting down")
            with self._lock:
                if job.evicted:
                    raise InterruptedError("job evicted")
                job.push(pct, msg)

        try:
            result = func(params, progress)
            if hasattr(result, "model_dump"):
                result = result.model_dump()
            with self._lock:
                if job.evicted:
                    return
                job.result = result
                job.status = "done"
                job.push(100.0, job.message or "done")
                self._evict_old_jobs()
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            with self._lock:
                if job.evicted:
                    return
                job.status = "error"
                job.error = f"{e.__class__.__name__}: {e}\n{traceback.format_exc(limit=5)}"
                self._evict_old_jobs()

    def _evict_old_jobs(self) -> None:
        """Remove abandoned running jobs and the oldest completed jobs.

        Caller must hold ``_lock``.
        """
        now = time.time()
        # Running jobs past MAX_JOB_AGE_S are presumed stuck (blocked thread,
        # hung upstream call). Mark them terminal so their (possibly large)
        # result payload is released with the rest of the dict entry.
        abandoned = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status == "running" and (now - job.created_at) > MAX_JOB_AGE_S
        ]
        for job_id in abandoned:
            job = self._jobs.pop(job_id, None)
            if job is not None:
                job.evicted = True
                job.status = "error"
                job.error = "job evicted: exceeded max age"
                job.result = None
                job.events.clear()

        if len(self._jobs) <= self._max_history:
            return
        completed = sorted(
            ((job_id, job) for job_id, job in self._jobs.items() if job.status in ("done", "error")),
            key=lambda item: item[1].created_at,
        )
        for job_id, _ in completed[: len(self._jobs) - self._max_history]:
            job = self._jobs.pop(job_id, None)
            if job is not None:
                job.evicted = True
                job.result = None
                job.events.clear()

    def release(self, job_id: str) -> None:
        """Drop a completed job's result payload, keeping its terminal status.

        Called by the client after it has consumed the result, so the
        retained set stays bounded by active jobs rather than history depth.
        Idempotent: unknown or already-released jobs are a no-op.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.result = None
                # Keep the terminal event for late SSE subscribers, drop the rest
                if job.events:
                    last = job.events[-1]
                    job.events.clear()
                    job.events.append(last)

    def snapshot(self, job_id: str) -> dict | None:
        """Return a consistent job response while holding the manager lock."""
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job is not None else None

    def events_since(self, job_id: str, seen: int) -> tuple[list[dict], str, dict] | None:
        """Return (events newer than `seen`, status, snapshot).

        `seen` is a monotonic sequence number (the `seq` of the last event
        the caller processed), NOT a list index. If the deque has dropped
        events the caller hasn't seen, those are silently skipped — the
        alternative (blocking the ring buffer) would grow memory without
        bound for a stalled consumer.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            # deque is small (<=500); linear scan is fine and avoids a
            # bisect dance over a possibly-wrapped deque.
            batch = [ev for ev in job.events if ev["seq"] > seen]
            return batch, job.status, job.to_dict()


jobs = JobManager()
