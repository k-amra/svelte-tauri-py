"""Verify the hand-written TS interfaces mirror the Pydantic models.

This is a heuristic field-name check, not a TypeScript parser. It catches
the most common drift mode (a field renamed or removed on one side) and
deliberately tolerates optional backend fields the UI doesn't surface yet.
The mirror is strict in the other direction: a TS field with no Pydantic
counterpart fails, so UI-only additions belong in non-mirrored types.

If you add a *required* backend field, this test fails until the TS mirror
is updated. That's the point.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.scripts.chat_stats import Params, Result
from app.scripts.chat_stats import models as chat_models

# src-python/tests/test_typescript_types.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
TS_FILE = REPO_ROOT / "src" / "lib" / "api" / "chatStats.ts"


def _ts_interface_fields(
    ts: str, name: str, _seen: frozenset[str] = frozenset()
) -> set[str]:
    """Extract field names from `export interface <name> { ... }`.

    Follows a single `extends` clause (e.g. `ChannelStatsResult extends
    ChatStatsResult`), mirroring TypeScript inheritance — otherwise every
    inherited required field would read as missing.
    """
    m = re.search(
        rf"export\s+interface\s+{re.escape(name)}\b(?:\s+extends\s+([A-Za-z_][A-Za-z0-9_]*))?\s*\{{(.*?)\n\}}",
        ts,
        re.DOTALL,
    )
    if not m:
        raise AssertionError(f"interface {name} not found in {TS_FILE}")
    fields: set[str] = set()
    for line in m.group(2).splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("/*"):
            continue
        m2 = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\??\s*:", line)
        if m2:
            fields.add(m2.group(1))
    parent = m.group(1)
    if parent and parent not in _seen:
        fields |= _ts_interface_fields(ts, parent, _seen | {name})
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
        (chat_models.TopChatterStat, "TopChatterStat"),
        (chat_models.DayCount, "DayCount"),
        (chat_models.TrendPoint, "TrendPoint"),
        (chat_models.WordCount, "WordCount"),
        (chat_models.EmoteCount, "EmoteCount"),
        (chat_models.EmotePairCount, "EmotePairCount"),
        (chat_models.CommandCount, "CommandCount"),
        (chat_models.DomainCount, "DomainCount"),
        (chat_models.UrlCount, "UrlCount"),
        (chat_models.MentionCount, "MentionCount"),
        (chat_models.MentionPair, "MentionPair"),
        (chat_models.MentionDegree, "MentionDegree"),
        (chat_models.MutualMentionPair, "MutualMentionPair"),
        (chat_models.EmoteCentrality, "EmoteCentrality"),
        (chat_models.LorenzSample, "LorenzSample"),
        (chat_models.BotScore, "BotScore"),
        (chat_models.CohortCell, "CohortCell"),
        (chat_models.CohortRow, "CohortRow"),
        (chat_models.DayLanguage, "DayLanguage"),
        (chat_models.RepeatedMessage, "RepeatedMessage"),
        (chat_models.RoleCount, "RoleCount"),
        (chat_models.StaffMember, "StaffMember"),
        (chat_models.SessionStats, "SessionStats"),
        (chat_models.Concentration, "Concentration"),
        (chat_models.MessageClassStats, "MessageClassStats"),
        (chat_models.PhraseCount, "PhraseCount"),
        (chat_models.PlatformLinks, "PlatformLinks"),
        (chat_models.PeakStat, "PeakStat"),
        (chat_models.ChatterDist, "ChatterDist"),
        (chat_models.ActivityPerDayStats, "ActivityPerDayStats"),
        (chat_models.LanguageBreakdown, "LanguageBreakdown"),
        (chat_models.AnomalyStat, "AnomalyStat"),
        (chat_models.QuoteReplyPair, "QuoteReplyPair"),
        (chat_models.EmoteDiversityStat, "EmoteDiversityStat"),
        (chat_models.CopyPasteChain, "CopyPasteChain"),
        (chat_models.ChannelSummary, "ChannelSummary"),
        (chat_models.ChatterDelta, "ChatterDelta"),
        (chat_models.PreviousPeriod, "PreviousPeriod"),
        (chat_models.ChannelResult, "ChannelStatsResult"),
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
