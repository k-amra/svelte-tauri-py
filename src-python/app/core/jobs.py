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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


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
    events: list[dict] = field(default_factory=list)

    def push(self, pct: float, msg: str = "") -> None:
        self.progress = pct
        self.message = msg
        self.events.append({"progress": pct, "message": msg, "t": time.time()})

    def to_dict(self) -> dict:
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
        self._max_history = 100
        self._shutdown = threading.Event()

    def request_shutdown(self) -> None:
        """Signal running jobs to abort at their next progress() checkpoint."""
        self._shutdown.set()

    def submit(self, script: str, func: Callable, params: Any) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], script=script)
        with self._lock:
            self._jobs[job.id] = job
        t = threading.Thread(target=self._run, args=(job, func, params), daemon=True)
        t.start()
        return job

    def _run(self, job: Job, func: Callable, params: Any) -> None:
        def progress(pct: float, msg: str = "") -> None:
            if self._shutdown.is_set():
                raise InterruptedError("server shutting down")
            with self._lock:
                job.push(pct, msg)

        try:
            result = func(params, progress)
            if hasattr(result, "model_dump"):
                result = result.model_dump()
            with self._lock:
                job.result = result
                job.status = "done"
                job.push(100.0, job.message or "done")
                self._evict_old_jobs()
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            with self._lock:
                job.status = "error"
                job.error = f"{e.__class__.__name__}: {e}\n{traceback.format_exc(limit=5)}"
                self._evict_old_jobs()

    def _evict_old_jobs(self) -> None:
        """Remove the oldest completed jobs; caller must hold ``_lock``."""
        if len(self._jobs) <= self._max_history:
            return
        completed = sorted(
            ((job_id, job) for job_id, job in self._jobs.items() if job.status in ("done", "error")),
            key=lambda item: item[1].created_at,
        )
        for job_id, _ in completed[: len(self._jobs) - self._max_history]:
            del self._jobs[job_id]

    def snapshot(self, job_id: str) -> dict | None:
        """Return a consistent job response while holding the manager lock."""
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job is not None else None

    def events_since(self, job_id: str, seen: int) -> tuple[list[dict], str, dict] | None:
        """Copy events and status atomically for the SSE endpoint."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return list(job.events[seen:]), job.status, job.to_dict()


jobs = JobManager()
