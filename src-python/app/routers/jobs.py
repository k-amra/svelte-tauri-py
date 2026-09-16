"""Jobs API for long-running scripts (>2s). Thin adapter over core/jobs.py."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class JobRequest(BaseModel):
    script: str
    params: dict = {}


@router.post("/jobs")
async def create_job(req: JobRequest):
    from app.core.jobs import jobs
    from app.scripts import registry

    mod = registry.REGISTRY.get(req.script)
    if mod is None:
        raise HTTPException(404, f"unknown script: {req.script}")
    try:
        parsed = mod.Params(**req.params)
    except Exception as e:
        raise HTTPException(422, str(e)) from e
    job = jobs.submit(req.script, mod.run, parsed)
    return jobs.snapshot(job.id)


@router.post("/jobs/{job_id}/ack")
async def ack_job(job_id: str):
    """Drop a completed job's result payload after the client has consumed it.

    Best-effort and idempotent: unknown/evicted jobs are a no-op, and a job
    that is still running is left alone (release only nulls the result).
    """
    from app.core.jobs import jobs

    jobs.release(job_id)
    return {"status": "ok"}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    from app.core.jobs import jobs

    snapshot = jobs.snapshot(job_id)
    if snapshot is None:
        raise HTTPException(404, f"unknown job: {job_id}")
    return snapshot


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str):
    from app.core.jobs import jobs

    async def gen():
        seen = -1  # start before the first event (seq starts at 0)
        last_heartbeat = time.time()
        while True:
            batch = jobs.events_since(job_id, seen)
            if batch is None:
                # Shape the terminal error frame like a JobStatus so the
                # client's `JSON.parse(msg.data) as JobStatus` path stays
                # type-correct (e.g. its polling fallback reads .status).
                error_snapshot = {
                    "job_id": job_id,
                    "script": "",
                    "status": "error",
                    "progress": 0.0,
                    "message": "",
                    "result": None,
                    "error": f"unknown job: {job_id}",
                }
                yield f"event: error\ndata: {json.dumps(error_snapshot)}\n\n"
                return
            events, status, snapshot = batch
            for ev in events:
                yield f"data: {json.dumps(ev)}\n\n"
                seen = ev["seq"]
            if status in ("done", "error"):
                yield f"event: {status}\ndata: {json.dumps(snapshot)}\n\n"
                return
            # SSE comment: keeps idle connections alive through proxies and
            # WebViews that drop quiet streams. Clients must ignore `:` lines
            # (readSSE does) — this frame carries no event and no data.
            if time.time() - last_heartbeat > 15:
                yield ": heartbeat\n\n"
                last_heartbeat = time.time()
            await asyncio.sleep(0.2)

    return StreamingResponse(gen(), media_type="text/event-stream")
