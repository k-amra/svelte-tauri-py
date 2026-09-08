"""Example capability. Copy this file to add a new Python capability.

Contract (see plan.md §4 + AGENTS.md):
- Pydantic `Params` and `Result` models
- `NAME`, `DESCRIPTION` strings
- `run(params: Params, progress=lambda pct, msg="": None) -> Result`
"""

from __future__ import annotations

import time
from collections.abc import Callable

from pydantic import BaseModel, Field


class Params(BaseModel):
    input_path: str = Field(description="Input value or path to process")
    threshold: float = 0.5


class Result(BaseModel):
    count: int
    output_path: str


NAME = "example_task"
DESCRIPTION = "Counts things above a threshold."


def run(params: Params, progress: Callable[[float, str], None] = lambda pct, msg="": None) -> Result:
    progress(10.0, "starting")
    # Simulate chunked work so progress/SSE can be observed.
    needle = str(params.input_path)
    haystack = f"{needle}\n" * 10
    count = sum(1 for line in haystack.splitlines() if len(line) * params.threshold >= 1)
    for pct in (40.0, 70.0):
        time.sleep(0.05)
        progress(pct, f"working ({pct:.0f}%)")
    progress(100.0, "done")
    return Result(count=count, output_path=f"{needle}.out")
