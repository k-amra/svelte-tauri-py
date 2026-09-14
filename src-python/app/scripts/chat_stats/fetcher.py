"""Fetch channel logs (month by month, cached) and return a merged dataframe.

This module owns the execution/caching layer that used to live at the bottom
of `chat_stats.py`. It is deliberately independent of `orchestrator.py` — the
public `run()` in `__init__.py` ties the two together.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import polars as pl

from app.services import log_cache
from app.services.emotes import fetch_channel_emotes
from app.services.harambelogs_client import HarambelogsAPI, HarambelogsError
from app.services.harambelogs_models import FullMessage
from app.services.log_fetch import (
    RETRYABLE_STATUS_CODES,
    channel_log_days,
    fetch_channel_logs,
)

from .constants import (
    PROGRESS_MSG_THRESHOLD,
    SPAN_RETRY_COOLDOWN_S,
    SPAN_RETRY_TICK_S,
)
from .frame import dedupe_by_id, extract_twitch_id, messages_to_frame
from .models import Params

logger = logging.getLogger(__name__)


@dataclass
class MonthResult:
    """Per-month fetch result. Replaces the 5-tuple _run_month used to return."""

    frame: pl.DataFrame
    fetched: bool
    truncated: bool
    twitch_id: str | None
    cached_at: float | None


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _get_months_range(from_date: datetime, to_date: datetime) -> list[tuple[int, int]]:
    """Calendar months (year, month) covering [from_date, to_date)."""
    months: list[tuple[int, int]] = []
    year, month = from_date.year, from_date.month
    while (year, month) <= (to_date.year, to_date.month):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _coverage_gaps(
    intervals: list[tuple[datetime, datetime]],
    need_from: datetime,
    need_to: datetime,
) -> list[tuple[datetime, datetime]]:
    """Parts of [need_from, need_to] not covered by any interval, in order."""
    gaps: list[tuple[datetime, datetime]] = []
    cursor = need_from
    for start, end in sorted(intervals):
        if end <= cursor:
            continue
        if start > cursor:
            gaps.append((cursor, min(start, need_to)))
        cursor = max(cursor, end)
        if cursor >= need_to:
            break
    if cursor < need_to:
        gaps.append((cursor, need_to))
    return gaps


def _month_progress(
    progress: Callable[[float, str], None], base: float, span: float, label: str
) -> Callable[[int, list[FullMessage]], None]:
    """Per-page progress scoped to one month's slice of the fetch budget.

    Pages complete out of order under concurrency, so progress is driven by
    the completion count (monotonic), not the page index. Updates are
    throttled to ~every 2000 messages: each push() appends to the job's
    event list, and hundreds of per-page pushes bloat polling payloads.
    Every push is also an abort checkpoint (InterruptedError on shutdown).
    """
    total = 0
    done_pages = 0
    last_update = 0
    peak = base

    def on_page(page: int, page_messages: list[FullMessage]) -> None:
        nonlocal total, done_pages, last_update, peak
        total += len(page_messages)
        done_pages += 1
        if done_pages == 1 or total - last_update >= PROGRESS_MSG_THRESHOLD:
            last_update = total
            peak = max(peak, base + span * (1.0 - 0.9**done_pages))
            progress(peak, f"{label}: fetched {total} messages ({done_pages} pages)")

    return on_page


async def _safe_fetch_emotes(channel: str, twitch_id: str | None) -> dict[str, str]:
    try:
        return await fetch_channel_emotes(channel, twitch_id)
    except Exception as e:
        logger.warning("Failed to fetch emotes for %s: %s", channel, e)
        return {}


async def _fetch_span(
    api: HarambelogsAPI,
    params: Params,
    span_from: datetime,
    span_to: datetime,
    on_page: Callable[[int, list[FullMessage]], None],
) -> tuple[list[FullMessage], bool]:
    return await fetch_channel_logs(
        api,
        params.channel_id_type,
        params.channel,
        span_from,
        span_to,
        on_page=on_page,
    )


async def _fetch_span_resilient(
    api: HarambelogsAPI,
    params: Params,
    span_from: datetime,
    span_to: datetime,
    on_page: Callable[[int, list[FullMessage]], None],
    label: str,
    progress: Callable[[float, str], None],
    base: float,
) -> tuple[list[FullMessage], bool]:
    """Fetch one span, retrying it once after a cooldown on transient errors.

    The retry re-requests the span from offset 0 (fetch_channel_logs is
    stateless) — acceptable because it only happens on rare transient
    failures. Non-retryable statuses fail fast, annotated with the month
    span so multi-month job errors stay diagnosable.
    """
    for attempt in (0, 1):
        try:
            return await _fetch_span(api, params, span_from, span_to, on_page)
        except HarambelogsError as e:
            if e.status_code not in RETRYABLE_STATUS_CODES or attempt == 1:
                raise HarambelogsError(
                    f"[{label} {span_from.date()}..{span_to.date()}] {e}",
                    status_code=e.status_code,
                ) from e
            # Countdown in ticks (not one long sleep) so each tick is an
            # abort checkpoint: progress() raises InterruptedError on shutdown.
            remaining = SPAN_RETRY_COOLDOWN_S
            while remaining > 0:
                progress(
                    base,
                    f"{label}: transient upstream error"
                    f" (HTTP {e.status_code or 'empty body'}) — retrying span in {remaining:.0f}s",
                )
                await asyncio.sleep(min(SPAN_RETRY_TICK_S, remaining))
                remaining -= SPAN_RETRY_TICK_S
    raise RuntimeError("unreachable")  # pragma: no cover


def _slice_range(df: pl.DataFrame, start: datetime, end: datetime) -> pl.DataFrame:
    # Half-open interval [start, end) so adjacent months don't both include
    # a message timestamped exactly at the boundary instant.
    return df.filter((pl.col("ts") >= start) & (pl.col("ts") < end))


def _span_extremes(df: pl.DataFrame) -> tuple[datetime | None, datetime | None]:
    if df.is_empty():
        return None, None
    lo = df["ts"].min()
    hi = df["ts"].max()
    return (lo, hi) if lo is not None and hi is not None else (None, None)


async def _run_month(
    api: HarambelogsAPI | None,
    params: Params,
    year: int,
    month: int,
    req_from: datetime,
    req_to: datetime,
    base: float,
    span: float,
    progress: Callable[[float, str], None],
) -> MonthResult:
    """Resolve one month of the requested range.

    Reuses the cached chunk when it covers the needed span and is fresh;
    otherwise downloads only the missing head/tail (or a delta top-up for
    stale live months) and merges it into the chunk.

    With ``force_refresh``, the full [need_from, need_to] span is always
    re-fetched — but the existing chunk is still loaded and merged into,
    so a partial-window refresh does not shrink the cached month.
    """
    label = f"{year}-{month:02d}"
    month_start, month_end = log_cache.month_bounds(year, month)
    need_from = max(req_from, month_start)
    need_to = min(req_to, month_end)
    if need_from >= need_to:
        # Zero-width need: the range ends exactly on this month's boundary,
        # so the previous month already covered everything. No fetch, no chunk.
        return MonthResult(messages_to_frame([]), False, False, None, None)

    # Always load the chunk (even on force_refresh) so a refresh can merge
    # into it rather than overwrite it with a partial-window frame.
    stored = log_cache.load_month(params.channel_id_type, params.channel, year, month, allow_stale=True)
    meta = stored[1] if stored else {}

    def finish(df: pl.DataFrame) -> MonthResult:
        return MonthResult(
            frame=_slice_range(df, need_from, need_to),
            fetched=False,
            truncated=bool(meta.get("truncated", False)),
            twitch_id=meta.get("twitch_id"),
            cached_at=meta.get("fetched_at"),
        )

    stored_cov = log_cache.coverage_intervals(meta) if stored is not None else []

    # Computed once and reused by both the cache-hit check and the span
    # planner below.
    fetched_at = float(meta.get("fetched_at", 0.0))
    stale = (
        not bool(meta.get("immutable"))
        and (time.time() - fetched_at) >= log_cache.LIVE_TTL_S
    )

    if stored is not None and not params.force_refresh:
        old_df = stored[0]
        covered_now = log_cache.covers(stored_cov, need_from, need_to)
        fresh = bool(meta.get("immutable")) or not stale
        covered_past = fetched_at >= need_to.timestamp()
        if covered_now and (fresh or covered_past):
            progress(base + span, f"cache hit: {label} ({old_df.height} messages)")
            return finish(old_df)

    if api is None:
        raise RuntimeError(f"Cache miss for {label} but no API client was provided.")

    on_page = _month_progress(progress, base, span, label)
    overlap = timedelta(minutes=10)
    spans: list[tuple[datetime, datetime]] = []

    if stored is None or params.force_refresh:
        spans.append((need_from, need_to))
    else:
        # Gaps within the need that no interval covers, each widened by the
        # overlap (clamped to the need) so boundary-exclusive upstreams can't
        # leave a hole the coverage then claims. Disjoint requests fetch
        # exactly their span — no bridging, no over-fetch.
        for gap_from, gap_to in _coverage_gaps(stored_cov, need_from, need_to):
            spans.append(
                (max(gap_from - overlap, need_from), min(gap_to + overlap, need_to))
            )

        # Stale live month: refresh what may have changed since the last
        # fetch. Note this preserves the delta top-up: with no gaps the only
        # span is [fetched_at - overlap, need_to], never the whole need.
        if stale:
            tail_from = max(need_from, datetime.fromtimestamp(fetched_at, UTC) - overlap)
            if tail_from < need_to:
                if spans and spans[-1][1] >= tail_from:
                    spans[-1] = (min(spans[-1][0], tail_from), max(spans[-1][1], need_to))
                else:
                    spans.append((tail_from, need_to))

    if not spans:
        # Covered but nothing to refresh (e.g. capped purely by fetched_at
        # already past need_to): reuse without downloading.
        progress(base + span, f"cache hit: {label} ({stored[0].height} messages)")
        return finish(stored[0])

    progress(base, f"downloading {label}…")
    new_frames: list[pl.DataFrame] = []
    new_truncated = False
    new_twitch_id: str | None = None
    # Track coverage per span as it completes, so a truncated span can only
    # attest to what it actually attained — not to the global max of every
    # span combined (which would falsely cover later, completed gaps).
    new_cov = list(stored_cov)
    for span_from, span_to in spans:
        messages, span_truncated = await _fetch_span_resilient(
            api, params, span_from, span_to, on_page, label, progress, base
        )
        new_truncated = new_truncated or span_truncated
        if new_twitch_id is None:
            new_twitch_id = extract_twitch_id(messages)
        frame = messages_to_frame(messages)
        new_frames.append(frame)

        if span_truncated:
            # Coverage extends only to the actual high-water mark of THIS span.
            _, hi = _span_extremes(frame)
            if hi is not None and span_from < hi:
                new_cov = log_cache.merge_coverage(new_cov, (span_from, hi))
        else:
            new_cov = log_cache.merge_coverage(new_cov, (span_from, span_to))

    if stored is not None:
        merged = pl.concat([stored[0], *new_frames], how="vertical")
    else:
        merged = pl.concat(new_frames, how="vertical") if len(new_frames) > 1 else new_frames[0]
    merged = dedupe_by_id(merged).sort("ts")

    month_truncated = bool(meta.get("truncated", False)) or new_truncated
    complete = (
        not month_truncated
        and log_cache.covers(new_cov, month_start, month_end)
    )
    twitch_id = new_twitch_id or meta.get("twitch_id")

    log_cache.save_month(
        params.channel_id_type,
        params.channel,
        year,
        month,
        merged,
        {
            "channel": params.channel,
            "channel_id_type": params.channel_id_type,
            "year": year,
            "month": month,
            "fetched_at": time.time(),
            "immutable": log_cache.is_month_immutable(year, month),
            "truncated": month_truncated,
            # New canonical field: list of [from_iso, to_iso] intervals.
            "coverage": [[s.isoformat(), e.isoformat()] for s, e in new_cov],
            # Legacy fields, derived from the interval list for older readers.
            "covered_from": min((s for s, _ in new_cov), default=None).isoformat()
                if new_cov else None,
            "covered_to": max((e for _, e in new_cov), default=None).isoformat()
                if new_cov else None,
            "complete": complete,
            "message_count": merged.height,
            "twitch_id": twitch_id,
        },
    )

    progress(base + span, f"merging {label} with cache")
    return MonthResult(
        frame=_slice_range(merged, need_from, need_to),
        fetched=True,
        truncated=month_truncated,
        twitch_id=twitch_id,
        cached_at=None,
    )


async def _run_chunked(
    params: Params,
    progress: Callable[[float, str], None],
    api: HarambelogsAPI | None = None,
    channel: str | None = None,
    channel_id_type: str | None = None,
) -> tuple[pl.DataFrame, bool, bool, str | None, str | None, bool]:
    """Fetch the range month by month.

    If `api` is None and a fetch is needed, owns a client for the duration;
    otherwise reuses the caller-provided client. See `_run_chunked_with_api`
    for the body and the cache-hit reasoning.

    `channel` / `channel_id_type` override `params.channel` for multi-channel
    runs (single-channel callers pass nothing and get params.channel). The
    override is applied by rebinding params so every helper downstream
    (`_run_month`, cache keys) sees the right channel.

    Returns ``(frame, any_fetch, truncated, twitch_id, cached_at,
    range_fully_outside)``. ``cached_at`` is set only when every month came
    from cache; ``range_fully_outside`` is True when the whole requested range
    sits outside the channel's logged calendar.
    """
    if channel is not None:
        params = params.model_copy(
            update={
                "channel": channel,
                "channel_id_type": channel_id_type or params.channel_id_type,
            }
        )
    req_from = _as_utc(params.from_date)
    req_to = _as_utc(params.to_date)
    months = _get_months_range(req_from, req_to)

    progress(2.0, "planning fetch")
    needs_fetch = params.force_refresh
    if not needs_fetch:
        # Local-only hit check; mirrors _run_month's reuse condition
        # (covers + fresh-or-covered-past — the latter may still resolve
        # to a hit inside _run_month, at the cost of one calendar probe).
        for year, month in months:
            month_start, month_end = log_cache.month_bounds(year, month)
            need_from = max(req_from, month_start)
            need_to = min(req_to, month_end)
            if need_from >= need_to:
                continue
            chunk = log_cache.load_month(params.channel_id_type, params.channel, year, month)
            if chunk is None:
                needs_fetch = True
                break
            _, meta = chunk
            if not log_cache.covers(log_cache.coverage_intervals(meta), need_from, need_to):
                needs_fetch = True
                break

    if api is not None or not needs_fetch:
        # Caller gave us a client, or we don't need one. (When needs_fetch is
        # False, `_run_month` will hit cache for every month, so api=None is
        # safe — its guard only fires on an actual cache miss.)
        return await _run_chunked_with_api(
            api, params, req_from, req_to, months, progress, needs_fetch
        )

    async with HarambelogsAPI() as owned:
        return await _run_chunked_with_api(
            owned, params, req_from, req_to, months, progress, needs_fetch
        )


async def _run_chunked_with_api(
    api: HarambelogsAPI | None,
    params: Params,
    req_from: datetime,
    req_to: datetime,
    months: list[tuple[int, int]],
    progress: Callable[[float, str], None],
    needs_fetch: bool,
) -> tuple[pl.DataFrame, bool, bool, str | None, str | None, bool]:
    """Body of `_run_chunked` once client ownership is resolved.

    Two phases: first decide purely locally (chunk validity) whether any
    month needs downloading at all — a full hit stays fully offline. Only
    then, the requested range is clamped once to the channel's logged
    calendar, so pre-history/future edges never hit the network at all.
    """
    range_fully_outside = False
    if needs_fetch and api is not None:
        days = await channel_log_days(api, params.channel_id_type, params.channel)
        if days:
            first_day = min(days)
            last_day = max(days)
            first = datetime(first_day.year, first_day.month, first_day.day, tzinfo=UTC)
            last_end = datetime(last_day.year, last_day.month, last_day.day, tzinfo=UTC) + timedelta(days=1)
            clamped_from = max(req_from, first)
            clamped_to = min(req_to, last_end)
            if clamped_from >= clamped_to:
                # Entirely outside the logged calendar — surface this instead
                # of silently returning a clean zero-stat result.
                range_fully_outside = True
            elif clamped_from != req_from or clamped_to != req_to:
                progress(
                    2.0,
                    f"range clamped to logged history ({clamped_from.date()}..{clamped_to.date()})",
                )
            req_from, req_to = clamped_from, clamped_to
            months = _get_months_range(req_from, req_to) if req_from < req_to else []

    total = len(months)
    parts: list[pl.DataFrame] = []
    any_fetch = False
    overall_truncated = False
    twitch_id: str | None = None
    newest_cached_at: float | None = None

    for i, (year, month) in enumerate(months):
        base = 2.0 + 76.0 * (i / total) if total > 0 else 2.0
        span = 76.0 / total if total > 0 else 76.0
        result = await _run_month(api, params, year, month, req_from, req_to, base, span, progress)
        parts.append(result.frame)
        any_fetch = any_fetch or result.fetched
        overall_truncated = overall_truncated or result.truncated
        if result.twitch_id is not None and twitch_id is None:
            twitch_id = result.twitch_id
        if result.cached_at is not None and not result.fetched:
            newest_cached_at = (
                result.cached_at if newest_cached_at is None else max(newest_cached_at, result.cached_at)
            )

    df = pl.concat(parts, how="vertical") if parts else messages_to_frame([])
    # Final dedupe: month parts can share an id at their boundaries, and
    # adjacent months' half-open slices eliminate the instant, but a
    # boundary-spanning overlap-update can still produce duplicates.
    df = dedupe_by_id(df).sort("ts")

    cached_at = (
        _as_utc(datetime.fromtimestamp(newest_cached_at, UTC)).isoformat()
        if (not any_fetch and newest_cached_at is not None)
        else None
    )
    return df, any_fetch, overall_truncated, twitch_id, cached_at, range_fully_outside


async def run_all(
    params: Params,
    progress: Callable[[float, str], None],
    api: HarambelogsAPI | None = None,
) -> tuple[pl.DataFrame, bool, bool, str | None, str | None, list[dict[str, str]], dict[str, str], list[str]]:
    """Fetch all channels; returns per-channel emote maps plus their union.

    Returns ``(frame, any_fetch, truncated, twitch_id, cached_at,
    emote_maps, union_emotes, outside_channels)``. ``emote_maps[i]``
    aligns with ``params.channels[i]`` so callers can compute accurate
    per-channel stats; ``union_emotes`` is what the pooled run uses.
    ``outside_channels`` lists channels whose requested range sits entirely
    outside their logged history (empty when none)."""
    # Single-channel fast path — identical to the pre-multi-channel behavior.
    if len(params.channels) <= 1:
        ch = params.channels[0] if params.channels else (params.channel or "")
        df, any_fetch, truncated, twitch_id, cached_at, fully_outside = await _run_chunked(
            params, progress, api=api
        )
        progress(80.0, "fetching emotes")
        emote_map = await _safe_fetch_emotes(ch, twitch_id)
        return df, any_fetch, truncated, twitch_id, cached_at, [emote_map], emote_map, (
            [ch] if fully_outside else []
        )

    # Multi-channel path: fetch each channel sequentially (the fetcher already
    # runs 5 concurrent page requests per channel; gathering channels on top
    # would multiply upstream pressure and risk rate limiting), tag every row
    # with its channel, and pool the frames.
    frames: list[pl.DataFrame] = []
    emote_maps: list[dict[str, str]] = []
    any_fetch_all = False
    truncated_all = False
    newest_cached_at: float | None = None
    outside_channels: list[str] = []
    n = len(params.channels)

    for i, ch in enumerate(params.channels):
        # Each channel gets [i/n, (i+1)/n] of the fetch budget (2%..78%).
        def sub_progress(pct: float, msg: str, _i=i, _ch=ch) -> None:
            progress(2.0 + 76.0 * ((_i + pct / 100.0) / n), f"[{_ch}] {msg}")

        df, any_fetch, truncated, twitch_id, cached_at, fully_outside = await _run_chunked(
            params, sub_progress, api=api, channel=ch, channel_id_type=params.channel_id_type
        )
        # Tag every row with the channel name (messages_to_frame doesn't add one).
        df = df.with_columns(pl.lit(ch).alias("channel"))
        frames.append(df)
        any_fetch_all = any_fetch_all or any_fetch
        truncated_all = truncated_all or truncated
        if fully_outside:
            outside_channels.append(ch)
        if cached_at is not None and not any_fetch:
            newest_cached_at = (
                _as_utc(datetime.fromisoformat(cached_at)).timestamp()
                if newest_cached_at is None
                else max(newest_cached_at, _as_utc(datetime.fromisoformat(cached_at)).timestamp())
            )

        progress(78.0 + (i + 1) / n * 2.0, f"[{ch}] fetching emotes")
        emote_maps.append(await _safe_fetch_emotes(ch, twitch_id))

    merged = pl.concat(frames, how="vertical").sort("ts")
    # Message ids are globally unique per Twitch message, so cross-channel
    # collisions shouldn't happen; dedupe anyway to preserve the one-row-per-
    # message invariant.
    merged = dedupe_by_id(merged)

    # Union of emote maps. On name collision the later channel wins; emote
    # names are unique per channel but not across the union, and either
    # mapping is fine for name-based text matching.
    union_emotes: dict[str, str] = {}
    for em in emote_maps:
        union_emotes.update(em)

    cached_at = (
        _as_utc(datetime.fromtimestamp(newest_cached_at, UTC)).isoformat()
        if (not any_fetch_all and newest_cached_at is not None)
        else None
    )
    return merged, any_fetch_all, truncated_all, None, cached_at, emote_maps, union_emotes, outside_channels
