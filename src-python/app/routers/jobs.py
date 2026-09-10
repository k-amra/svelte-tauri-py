"""Jobs API for long-running scripts (>2s). Thin adapter over core/jobs.py."""

from __future__ import annotations

import asyncio
import json

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
        while True:
            batch = jobs.events_since(job_id, seen)
            if batch is None:
                yield f"event: error\ndata: {json.dumps({'error': 'unknown job'})}\n\n"
                return
            events, status, snapshot = batch
            for ev in events:
                yield f"data: {json.dumps(ev)}\n\n"
                seen = ev["seq"]
            if status in ("done", "error"):
                yield f"event: {status}\ndata: {json.dumps(snapshot)}\n\n"
                return
            await asyncio.sleep(0.2)

    return StreamingResponse(gen(), media_type="text/event-stream")
