"""Advanced polars statistics over a channel's chat logs (polars-powered) - v4.5.

Execution model: full channel log fetches routinely exceed 2s, so this is
meant to run through the jobs API (POST /api/jobs), which executes it in a
worker thread with progress callbacks and shutdown interruption.

Timezone: upstream timestamps are treated as UTC; time-bucketed stats are UTC.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta

import polars as pl

from app.services.harambelogs_client import HarambelogsAPI

from .analytics.anomalies import poisson_lower_tail, poisson_upper_tail
from .analytics.health import (
    compute_copy_paste_chains,
    compute_health,
    compute_message_classes,
    compute_non_ascii,
    compute_roles,
    compute_self_repetition,
)
from .analytics.links import compute_links
from .analytics.overview import compute_overview
from .analytics.temporal import compute_time, decompose_weekly_seasonality
from .constants import STOPWORDS
from .fetcher import run_all
from .frame import clean_text_expr, messages_to_frame, parse_twitch_emotes
from .models import (
    ChannelResult,
    ChannelSummary,
    ChatterDelta,
    DayCount,
    Params,
    PreviousPeriod,
    Result,
)
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


# --- Previous-period helpers ------------------------------------------------


def _chatter_counts(df: pl.DataFrame) -> dict[str, tuple[str, int]]:
    """`user_id -> (username, message_count)`; empty df yields an empty dict."""
    if df.is_empty():
        return {}
    agg = df.group_by("user_id").agg(
        pl.col("username").last().alias("username"),
        pl.len().alias("n"),
    )
    return {r["user_id"]: (r["username"], int(r["n"])) for r in agg.iter_rows(named=True)}


def _top_movers(
    current_df: pl.DataFrame,
    previous_df: pl.DataFrame,
    top_n: int = 5,
) -> tuple[list[ChatterDelta], list[ChatterDelta]]:
    """Top gainers and top losers by absolute message-count change.

    Uses the *full* user sets of both frames, not just `top_chatters` (which is
    capped at the user's `top_n`) — a user outside the current top-N can still
    be a meaningful gainer or loser.
    """
    curr = _chatter_counts(current_df)
    prev = _chatter_counts(previous_df)
    if not curr or not prev:
        # No baseline: everything would look like a "new gainer", which is noise.
        return [], []

    deltas: list[ChatterDelta] = []
    for uid in set(curr) | set(prev):
        c_name, c_n = curr.get(uid, ("", 0))
        p_name, p_n = prev.get(uid, ("", 0))
        if c_n == p_n:
            continue
        deltas.append(
            ChatterDelta(
                user_id=uid,
                username=c_name or p_name,
                current=c_n,
                previous=p_n,
                delta=c_n - p_n,
            )
        )

    if not deltas:
        return [], []

    deltas.sort(key=lambda d: d.delta, reverse=True)
    gainers = [d for d in deltas if d.delta > 0][:top_n]
    losers = [d for d in reversed(deltas) if d.delta < 0][:top_n]
    return gainers, losers


def _resolve_comparison_window(params: Params) -> tuple[datetime, datetime]:
    """Resolve the [from, to) window to compare against, given the mode.

    Only `previous_period` scales with the request (matching its span).
    `previous_week` / `previous_month` / `previous_year` are fixed-length
    windows — deliberately, so a 3-day query can still be compared against
    a full week. When the two windows differ in length, scalar deltas still
    work and the chart overlays degrade to single-series (see OverlayBars).
    """
    mode = params.comparison_mode
    if mode == "custom":
        # Guaranteed non-None by Params._validate_comparison.
        assert params.compare_from_date is not None
        assert params.compare_to_date is not None
        return params.compare_from_date, params.compare_to_date
    if mode == "previous_week":
        return params.from_date - timedelta(days=7), params.from_date
    if mode == "previous_month":
        return params.from_date - timedelta(days=30), params.from_date
    if mode == "previous_year":
        # Calendar year-back (Feb 29 → Feb 28), not a fixed 365-day offset.
        try:
            year_ago = params.from_date.replace(year=params.from_date.year - 1)
        except ValueError:  # Feb 29 → Feb 28
            year_ago = params.from_date.replace(year=params.from_date.year - 1, day=28)
        return year_ago, params.from_date
    # previous_period (default): same-length window immediately before.
    span = params.to_date - params.from_date
    return params.from_date - span, params.from_date


async def _compute_previous_period(
    params: Params,
    current_df: pl.DataFrame,
    api: HarambelogsAPI,
) -> PreviousPeriod:
    """Fetch + summarize the window selected by `comparison_mode`.

    Shares the caller's HTTP client. The recursive params copy sets
    `compare_previous=False`, so the fetch never walks back through history.
    """
    prev_from, prev_to = _resolve_comparison_window(params)
    prev_params = params.model_copy(
        update={
            "from_date": prev_from,
            "to_date": prev_to,
            "compare_previous": False,
        }
    )
    df, _any_fetch, _trunc, _twitch, _cached, _emote_maps, emote_map, _outside = await run_all(
        prev_params, lambda p, m: None, api=api
    )

    from_iso = prev_params.from_date.isoformat()
    to_iso = prev_params.to_date.isoformat()

    if df.is_empty():
        return PreviousPeriod(
            from_date=from_iso,
            to_date=to_iso,
            total_messages=0,
            unique_chatters=0,
            avg_message_length=0.0,
            activity_by_hour=[0] * 24,
            mode=params.comparison_mode,
        )

    overview = compute_overview(df)
    time_stats = compute_time(df)
    twitch_emotes = parse_twitch_emotes(df)

    roles = compute_roles(df)["roles"]
    roles_map = {r["role"]: r["messages"] for r in roles}

    classes = compute_message_classes(df, twitch_emotes, emote_map)["message_classes"]
    platform_links = compute_links(df, top_n=0, all_urls_limit=0)["platform_links"]
    health = compute_health(df, top_n=0)
    self_rep = compute_self_repetition(df)
    non_ascii = compute_non_ascii(df)
    copy_paste = compute_copy_paste_chains(df)

    gainers, losers = _top_movers(current_df, df, top_n=5)

    messages_per_day = [
        DayCount(date=d["date"], count=int(d["count"])) for d in time_stats["messages_per_day"]
    ]

    return PreviousPeriod(
        from_date=from_iso,
        to_date=to_iso,
        total_messages=overview["total_messages"],
        unique_chatters=overview["unique_chatters"],
        avg_message_length=overview["avg_message_length"],
        median_message_length=overview.get("median_message_length"),
        max_message_length=overview.get("max_message_length"),
        avg_words_per_message=overview.get("avg_words_per_message"),
        vocab_richness=overview.get("vocab_richness"),
        unique_word_count=overview.get("unique_word_count", 0),
        peak_concurrent_chatters=time_stats.get("peak_concurrent_chatters"),
        roles=roles_map,
        message_classes=dict(classes),
        platform_links=dict(platform_links),
        self_repetition_count=self_rep["self_repetition_count"],
        duplicate_message_count=health["duplicate_message_count"],
        non_ascii_ratio=non_ascii["non_ascii_ratio"],
        cross_user_copy_paste_count=copy_paste["cross_user_copy_paste_count"],
        top_chatter_gainers=gainers,
        top_chatter_losers=losers,
        messages_per_day=messages_per_day,
        activity_by_hour=list(time_stats["activity_by_hour"]),
        mode=params.comparison_mode,
    )


# --- Entry point ------------------------------------------------------------


async def _run_both(params: Params, progress: Callable[[float, str], None]) -> Result:
    """Current + optional previous window, sharing one HTTP client when comparing."""
    if params.compare_previous:
        # Always own a client here: the previous window almost certainly needs
        # a fetch, and even a fully-cached current fetch benefits from having
        # the client ready for the emote fetch.
        async with HarambelogsAPI() as api:
            return await _run_both_with_api(params, progress, api)
    return await _run_both_with_api(params, progress, api=None)


async def _run_both_with_api(
    params: Params,
    progress: Callable[[float, str], None],
    api: HarambelogsAPI | None,
) -> Result:
    df, any_fetch, truncated, twitch_id, cached_at, emote_maps, union_emotes, outside_channels = (
        await run_all(params, progress, api=api)
    )

    progress(85.0, "building dataframe & computing stats")
    stats = compute_stats(df, params, union_emotes)
    stats["truncated"] = truncated
    stats["from_cache"] = not any_fetch
    stats["cached_at"] = cached_at

    if outside_channels:
        if len(outside_channels) == len(params.channels):
            reason = (
                "Requested range is entirely outside logged history — no messages "
                "exist for this span."
            )
        else:
            reason = (
                f"Requested range is entirely outside logged history for: "
                f"{', '.join(outside_channels)}."
            )
        stats["warnings"] = list(stats.get("warnings") or []) + [reason]

    if len(params.channels) > 1:
        progress(88.0, "computing per-channel summaries")
        from .analytics.per_channel import compute_channel_summary

        # Per-channel top-words needs the same emote-name stopwords the
        # pooled run uses, otherwise emote names would dominate every
        # channel's list identically.
        per_channel_stopwords = STOPWORDS | {v.lower() for v in union_emotes.values()}

        if df.is_empty():
            # No merged span to align day arrays to; emit zero summaries so
            # the UI still renders one card per channel.
            summaries = [
                ChannelSummary(channel=ch, total_messages=0, unique_chatters=0)
                for ch in params.channels
            ]
        else:
            summaries = [
                compute_channel_summary(
                    df,
                    ch,
                    union_emotes,
                    stopwords=per_channel_stopwords,
                    merged_min_date=df["ts"].min().date(),
                    merged_max_date=df["ts"].max().date(),
                )
                for ch in params.channels
            ]
        stats["channel_summaries"] = summaries

        extra: list[str] = []
        covered = sum(s.total_messages for s in summaries)
        total = stats.get("total_messages", 0)
        # A nonzero gap means a dedupe collision dropped rows — surface it so
        # the user knows the per-channel sums won't reconcile.
        if covered != total:
            extra.append(
                f"per-channel message counts sum to {covered} but total is {total}; "
                "duplicate message ids may have been dropped during merge."
            )
        empty_channels = [s.channel for s in summaries if s.total_messages == 0]
        if empty_channels:
            if len(empty_channels) == len(summaries):
                extra.append(
                    "no channel returned messages — check the spelling and the date range"
                )
            else:
                extra.append(
                    f"{', '.join(empty_channels)} returned no messages — check the spelling"
                )
        if extra:
            stats["warnings"] = list(stats.get("warnings") or []) + extra

        # Full isolated stats per channel so the frontend can render every
        # metric (emote diversity, copy-paste chains, anomalies, ...) in its
        # own dedicated view without a second backend run.
        progress(90.0, "computing full per-channel stats")
        per_channel_results: list[ChannelResult] = []
        has_channel_col = "channel" in df.columns

        # Single O(N) pass; the previous per-channel df.filter() was O(N·M).
        # Keys from partition_by are 1-tuples when partitioning by one column.
        channel_frames: dict[str, pl.DataFrame] = {}
        if has_channel_col:
            for key, sub in df.partition_by("channel", as_dict=True).items():
                name = key[0] if isinstance(key, tuple) else key
                channel_frames[name] = sub

        for i, ch in enumerate(params.channels):
            ch_df = channel_frames.get(ch) if has_channel_col else None
            ch_params = params.model_copy(
                update={"channels": [ch], "channel": ch, "compare_previous": False}
            )
            ch_emote_map = emote_maps[i] if i < len(emote_maps) else {}

            if ch_df is None or ch_df.is_empty():
                ch_stats = Result(
                    total_messages=0,
                    unique_chatters=0,
                    days_spanned=0,
                    avg_message_length=0.0,
                    truncated=False,
                    top_chatters=[],
                    activity_by_hour=[0] * 24,
                    activity_by_weekday_hour=[[0] * 24 for _ in range(7)],
                    messages_per_day=[],
                    top_words=[],
                    top_emotes=[],
                ).model_dump()
            else:
                ch_stats = compute_stats(ch_df, ch_params, ch_emote_map)
            # Pooled fetch metadata is the honest conservative default: if
            # nothing was fetched pooled, nothing was fetched per-channel.
            ch_stats["truncated"] = truncated
            ch_stats["from_cache"] = not any_fetch
            ch_stats["cached_at"] = cached_at
            per_channel_results.append(ChannelResult(channel=ch, **ch_stats))

        stats["per_channel"] = per_channel_results

    if params.compare_previous:
        if api is None:
            raise RuntimeError("compare_previous requires a shared HTTP client")
        progress(92.0, "computing previous period")
        stats["previous_period"] = await _compute_previous_period(params, df, api)

    progress(100.0, "done" if any_fetch else "done (cached)")
    return Result(**stats)


def run(
    params: Params,
    progress: Callable[[float, str], None] = lambda pct, msg="": None,
) -> Result:
    return asyncio.run(_run_both(params, progress))
