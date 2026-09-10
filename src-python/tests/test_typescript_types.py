"""Verify the hand-written TS interfaces mirror the Pydantic models.

This is a heuristic field-name check, not a TypeScript parser. It catches
the most common drift mode (a field renamed or removed on one side) and
deliberately tolerates:
- optional backend fields the UI doesn't surface yet
- extra non-model fields the UI adds (e.g. computed helper fields)

If you add a *required* backend field, this test fails until the TS mirror
is updated. That's the point.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.scripts.chat_stats import Params, Result

# src-python/tests/test_typescript_types.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
TS_FILE = REPO_ROOT / "src" / "lib" / "api" / "chatStats.ts"


def _ts_interface_fields(ts: str, name: str) -> set[str]:
    """Extract field names from `export interface <name> { ... }`."""
    m = re.search(rf"export\s+interface\s+{re.escape(name)}\s*\{{(.*?)\n\}}", ts, re.DOTALL)
    if not m:
        raise AssertionError(f"interface {name} not found in {TS_FILE}")
    fields: set[str] = set()
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("/*"):
            continue
        m2 = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\??\s*:", line)
        if m2:
            fields.add(m2.group(1))
    return fields


def _required_fields(model) -> set[str]:
    return {name for name, f in model.model_fields.items() if f.is_required()}


def _all_fields(model) -> set[str]:
    return set(model.model_fields.keys())


@pytest.mark.parametrize(
    "model, ts_name",
    [
        (Result, "ChatStatsResult"),
        (Params, "ChatStatsParams"),
    ],
)
def test_ts_mirror_matches_pydantic(model, ts_name: str) -> None:
    assert TS_FILE.exists(), f"missing {TS_FILE}"
    ts = TS_FILE.read_text(encoding="utf-8")
    ts_fields = _ts_interface_fields(ts, ts_name)

    py_all = _all_fields(model)
    py_required = _required_fields(model)

    missing_required = py_required - ts_fields
    assert not missing_required, (
        f"{ts_name} in {TS_FILE.name} is missing required backend fields: "
        f"{sorted(missing_required)}. Add them or make them optional in the model."
    )

    extras = ts_fields - py_all
    assert not extras, (
        f"{ts_name} in {TS_FILE.name} has fields that no longer exist on "
        f"{model.__name__}: {sorted(extras)}. Remove them."
    )
