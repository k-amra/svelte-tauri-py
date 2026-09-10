"""Paginated channel-log fetcher for analytics jobs.

Pages through ``GET /logs/channel/...`` with ``limit=1000`` until a short
page arrives. Pages are fetched concurrently — starting with a single
request and ramping up to ``CONCURRENCY`` while full pages keep arriving
(slow-start, so small channels cost one request and upstream never sees
more than a handful of simultaneous hits) — then merged back in offset
order. Caps total pages (huge channels would otherwise run forever) and
surfaces a ``truncated`` flag instead. Each completed page is a natural
progress checkpoint — and the place where ``InterruptedError`` from
``jobs.request_shutdown()`` surfaces, keeping jobs abortable (a failure in
any page cancels the rest).

Upstream quirks handled here (all live-verified):
- offset past the last message → 404 *or* zero-byte 200 (two flavors of
  the same refusal, not distinguishable by status alone);
- deep offsets (verified failing at 30k while offset 0 succeeds the same
  minute) are refused even with hundreds of thousands of messages behind
  them — so a span can NEVER be paginated past the refusal point.
Both flavors are disambiguated with a ``/stats`` messageCount probe:
``offset >= count`` (or count 0) means past-the-end/quiet → empty final
page; anything else with data behind it means refusal → the span is split
in half by time (offsets restart at 0) and fetched recursively. Without an
oracle answer nothing is ever synthesized: ambiguous signals fail loud.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime

from app.services.harambelogs_client import HarambelogsAPI, HarambelogsError
from app.services.harambelogs_models import (
    ChannelIdType,
    FullMessage,
    LogQueryParams,
)

PAGE_LIMIT = 1000
MAX_PAGES = 200  # 200 pages x 1000 = 200k messages max
PAGE_DELAY_S = 0.05  # brief stagger per request; throughput comes from concurrency
MAX_RETRIES = 5  # extra attempts per page on transient failures
CONCURRENCY = 5  # max simultaneous page requests (after slow-start ramp-up)
# Exponential backoff between page retries: upstream's zero-byte-2xx blips
# routinely outlive a 0.5s/1.0s pause. Waits 1,2,4,8,16s ≈ 31s of patience
# per page before giving up (also correct behaviour for 429s).
RETRY_BACKOFF_BASE_S = 1.0
RETRY_BACKOFF_CAP_S = 16.0
MAX_SPLIT_DEPTH = 8  # time-split recursion cap for deep-offset refusals

# Upstream uses 429 for rate limiting; 502/503/504 (and network errors,
# status_code=None) are worth one or two retries as well.
RETRYABLE_STATUS_CODES = frozenset({None, 429, 502, 503, 504})

OnPage = Callable[[int, list[FullMessage]], None]


def _is_retryable(e: HarambelogsError) -> bool:
    return e.status_code in RETRYABLE_STATUS_CODES


class _PaginationRefused(Exception):
    """Deep-offset refusal with oracle-confirmed data behind it.

    Raised when a 404/zero-byte page persists at an offset that still holds
    messages per ``/stats``. The span must be time-split (offsets restart at
    0), never retried in place. Internal to this module: the public wrapper
    converts it into split fetches, or a loud error past the depth cap.
    """

    def __init__(self, offset: int, count: int):
        super().__init__(f"upstream refuses pagination at offset {offset} ({count} messages in span)")
        self.offset = offset
        self.count = count


async def _span_message_count(
    api: HarambelogsAPI,
    channel_id_type: ChannelIdType,
    channel: str,
    from_date: datetime | None,
    to_date: datetime | None,
) -> int | None:
    """Upstream's own verdict on whether the span holds any messages.

    Oracle for ambiguous 404/zero-byte pages: 0 = quiet span,
    ``offset >= count`` = pagination past the end — both mean "empty page,
    stop". None = oracle unreachable; the caller stays loud, never guesses.
    """
    try:
        stats = await api.get_channel_stats(channel_id_type, channel, from_date, to_date)
        return stats.messageCount
    except Exception:  # noqa: BLE001 - the oracle must never break the fetch; None means "unknown"
        return None


def _dedupe(messages: list[FullMessage]) -> list[FullMessage]:
    """Stable dedupe for time-split merges (a boundary instant may repeat)."""
    seen: set = set()
    out: list[FullMessage] = []
    for m in messages:
        key = getattr(m, "id", None) or (
            getattr(m, "username", None),
            getattr(m, "text", None),
            str(getattr(m, "timestamp", None)),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    return out


async def channel_log_days(
    api: HarambelogsAPI,
    channel_id_type: ChannelIdType,
    channel: str,
) -> set[date] | None:
    """Logged calendar days for the channel, via ``GET /list?channel=``.

    Returns ``{"availableLogs": [{"year","month","day"}, ...]}`` as a set of
    dates, or None when unavailable/empty/unparseable. None is deliberately
    also returned for an empty calendar: a channel with zero logged days is
    indistinguishable from a typo, and that must stay a loud error, never
    silent zero-stats.
    """
    try:
        payload = await api.get_list(channel=channel)
    except Exception:  # noqa: BLE001 - no calendar, no clamping; downstream stays loud
        return None
    if not isinstance(payload, dict):
        return None
    entries = payload.get("availableLogs")
    if not entries or not isinstance(entries, list):
        return None
    days: set[date] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            days.add(date(int(entry["year"]), int(entry["month"]), int(entry["day"])))
        except (KeyError, TypeError, ValueError):
            continue
    return days or None


async def _fetch_page(
    api: HarambelogsAPI,
    channel_id_type: ChannelIdType,
    channel: str,
    from_date: datetime | None,
    to_date: datetime | None,
    offset: int,
) -> list[FullMessage]:
    """Fetch a single page with retries. Raises when retries are exhausted.

    A 404 at offset 0 still raises (unknown channel / out-of-range span).
    A 404 or zero-byte body at ``offset > 0`` — or a zero-byte body anywhere —
    is ambiguous (past-the-end/quiet vs upstream refusing deep offsets vs
    blip) and goes through the ``/stats`` oracle: confirmed empty means an
    empty final page; confirmed data gets one immediate retry (blips), then
    escalates to ``_PaginationRefused`` (time-split upstream). With no oracle
    answer nothing is synthesized: 404s raise, empty bodies take the legacy
    backoff path and fail loud on exhaustion.
    """
    await asyncio.sleep(PAGE_DELAY_S)
    params = LogQueryParams(limit=PAGE_LIMIT, offset=offset, json_=True)
    probed = False
    probed_count: int | None = None
    grace_used = False
    log_days: set[date] | None = None
    log_days_probed = False
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = await api.get_channel_logs(channel_id_type, channel, from_date, to_date, params)
            return resp.messages
        except HarambelogsError as e:
            if e.status_code == 404 and offset == 0:
                # A span with no logged day behind it (pre-history, future,
                # fully quiet month) is verified emptiness, not an error —
                # but only with a non-empty calendar to prove the channel
                # exists. Anything else stays loud. The check is half-open
                # ([from, to) by day) to match month-quantized needs: a need
                # ending exactly on a logged day belongs to the next span.
                if from_date is not None and to_date is not None:
                    if not log_days_probed:
                        log_days_probed = True
                        log_days = await channel_log_days(api, channel_id_type, channel)
                    if log_days and not any(
                        from_date.date() <= day < to_date.date() for day in log_days
                    ):
                        return []
                raise
            if e.status_code == 404 or e.empty_body:
                if not probed:
                    probed = True
                    probed_count = await _span_message_count(api, channel_id_type, channel, from_date, to_date)
                if probed_count is not None and (probed_count == 0 or offset >= probed_count):
                    return []
                if e.status_code == 404 and probed_count is None:
                    raise
                if not grace_used:
                    grace_used = True
                    continue  # one immediate retry shakes off blips
                if probed_count is not None:
                    raise _PaginationRefused(offset, probed_count) from e
                # else: empty body + dead oracle → legacy backoff below
            if not _is_retryable(e) or attempt >= MAX_RETRIES:
                raise
            await asyncio.sleep(min(RETRY_BACKOFF_CAP_S, RETRY_BACKOFF_BASE_S * 2**attempt))
    raise AssertionError("unreachable")  # pragma: no cover - loop returns or raises


async def _fetch_pages(
    api: HarambelogsAPI,
    channel_id_type: ChannelIdType,
    channel: str,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    *,
    on_page: OnPage | None = None,
    max_pages: int = MAX_PAGES,
) -> tuple[list[FullMessage], bool]:
    """Fetch all channel logs in the date range.

    Returns ``(messages, truncated)``. Pages complete out of order but are
    merged by offset before returning, so callers always see global order.
    Raises the ``HarambelogsError`` if a page keeps failing after retries
    (non-retryable errors raise immediately); in-flight pages are cancelled.
    May raise ``_PaginationRefused`` for the outer splitter.
    """
    if max_pages <= 0:
        return [], True

    semaphore = asyncio.Semaphore(CONCURRENCY)
    pages: dict[int, list[FullMessage]] = {}
    pending: set[asyncio.Task[tuple[int, list[FullMessage]]]] = set()
    spawned = 0
    parallelism = 1
    short_seen = False

    async def one(idx: int) -> tuple[int, list[FullMessage]]:
        async with semaphore:
            return idx, await _fetch_page(api, channel_id_type, channel, from_date, to_date, idx * PAGE_LIMIT)

    def spawn() -> None:
        nonlocal spawned
        task = asyncio.create_task(one(spawned))
        pending.add(task)
        spawned += 1

    spawn()  # slow-start: a single request, ramp up while full pages arrive
    try:
        while pending:
            done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                pending.discard(task)
                idx, page_messages = await task
                pages[idx] = page_messages
                if on_page is not None:
                    on_page(idx, page_messages)
                if len(page_messages) < PAGE_LIMIT:
                    short_seen = True
                else:
                    parallelism = min(CONCURRENCY, parallelism + 1)
                while not short_seen and spawned < max_pages and len(pending) < parallelism:
                    spawn()
    except BaseException:  # noqa: BLE001 - must catch CancelledError too, to stop siblings
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        raise

    messages: list[FullMessage] = []
    for idx in sorted(pages):
        messages.extend(pages[idx])
    truncated = not short_seen and spawned >= max_pages
    return messages, truncated


async def fetch_channel_logs(
    api: HarambelogsAPI,
    channel_id_type: ChannelIdType,
    channel: str,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    *,
    on_page: OnPage | None = None,
    max_pages: int = MAX_PAGES,
    _depth: int = 0,
) -> tuple[list[FullMessage], bool]:
    """Fetch all channel logs in the date range.

    Returns ``(messages, truncated)``. When upstream refuses deep offsets
    for a span that still holds data (``_PaginationRefused``), the span is
    split in half by time — offsets restart at 0 — and the halves are
    fetched recursively and merged (deduped, order-preserving). Splitting
    always converges (offsets shrink every level); past ``MAX_SPLIT_DEPTH``
    it fails loud. Progress callbacks are shared across halves and stay
    monotonic (driven by completion counts downstream).
    """
    try:
        return await _fetch_pages(
            api, channel_id_type, channel, from_date, to_date, on_page=on_page, max_pages=max_pages
        )
    except _PaginationRefused as r:
        if _depth >= MAX_SPLIT_DEPTH or from_date is None or to_date is None:
            raise HarambelogsError(
                f"upstream refuses deep pagination for span [{from_date}..{to_date}]"
                f" (stuck at offset {r.offset} of {r.count} messages); try again later",
                status_code=500,
            ) from r
        mid = from_date + (to_date - from_date) / 2
        if mid <= from_date or mid >= to_date:
            raise HarambelogsError(
                f"upstream refuses deep pagination for span [{from_date}..{to_date}]"
                f" (stuck at offset {r.offset} of {r.count} messages); try again later",
                status_code=500,
            ) from r
        left_msgs, left_trunc = await fetch_channel_logs(
            api, channel_id_type, channel, from_date, mid, on_page=on_page, max_pages=max_pages, _depth=_depth + 1
        )
        right_msgs, right_trunc = await fetch_channel_logs(
            api, channel_id_type, channel, mid, to_date, on_page=on_page, max_pages=max_pages, _depth=_depth + 1
        )
        return _dedupe(left_msgs + right_msgs), left_trunc or right_trunc
