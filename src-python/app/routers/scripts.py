"""Thin HTTP adapters over scripts/. No business logic here.

Auth is attached in main.py via include_router(dependencies=[Depends(verify_token)]).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/scripts")
async def list_scripts():
    from app.scripts import registry

    return registry.metadata()


@router.post("/scripts/{name}/run")
async def run_script(name: str, params: dict):
    from app.scripts import registry

    mod = registry.REGISTRY.get(name)
    if mod is None:
        raise HTTPException(404, f"unknown script: {name}")
    try:
        parsed = mod.Params(**params)
    except Exception as e:  # pydantic ValidationError -> 422
        raise HTTPException(422, str(e)) from e
    events: list = []

    def progress(pct: float, msg: str = "") -> None:
        events.append({"progress": pct, "message": msg})

    result = mod.run(parsed, progress)
    data = result.model_dump() if hasattr(result, "model_dump") else result
    return {"name": name, "result": data, "events": events}
