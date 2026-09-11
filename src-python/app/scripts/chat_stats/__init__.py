"""Advanced polars statistics over a channel's chat logs (polars-powered) - v4.5.

Execution model: full channel log fetches routinely exceed 2s, so this is
meant to run through the jobs API (POST /api/jobs), which executes it in a
worker thread with progress callbacks and shutdown interruption.

Timezone: upstream timestamps are treated as UTC; time-bucketed stats are UTC.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from .analytics.anomalies import poisson_lower_tail, poisson_upper_tail
from .analytics.health import compute_message_classes
from .analytics.temporal import decompose_weekly_seasonality
from .fetcher import run_all
from .frame import clean_text_expr, messages_to_frame, parse_twitch_emotes
from .models import Params, Result
from .orchestrator import compute_stats

NAME = "chat_stats"
DESCRIPTION = "Advanced polars statistics over a channel's chat logs (v4.5)."

__all__ = [
    "NAME",
    "DESCRIPTION",
    "Params",
    "Result",
    "run",
    "messages_to_frame",
    "compute_stats",
    "clean_text_expr",
    "parse_twitch_emotes",
    "compute_message_classes",
    "poisson_upper_tail",
    "poisson_lower_tail",
    "decompose_weekly_seasonality",
]


def run(
    params: Params,
    progress: Callable[[float, str], None] = lambda pct, msg="": None,
) -> Result:
    # from_date < to_date is enforced by Params._validate_date_order.
    df, any_fetch, truncated, twitch_id, cached_at, emote_map = asyncio.run(
        run_all(params, progress)
    )

    progress(85.0, "building dataframe & computing stats")
    stats = compute_stats(df, params, emote_map)
    stats["truncated"] = truncated
    stats["from_cache"] = not any_fetch
    stats["cached_at"] = cached_at
    progress(100.0, "done" if any_fetch else "done (cached)")
    return Result(**stats)
