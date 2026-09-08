"""Paginated channel-log fetcher for analytics jobs.

Pages through ``GET /logs/channel/...`` with ``limit=1000`` until a short
page arrives. Caps total pages (huge channels would otherwise run forever)
and surfaces a ``truncated`` flag instead. Each page is a natural progress
checkpoint — and the place where ``InterruptedError`` from
``jobs.request_shutdown()`` surfaces, keeping jobs abortable.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from app.services.harambelogs_client import HarambelogsAPI, HarambelogsError
from app.services.harambelogs_models import (
    ChannelIdType,
    FullMessage,
    LogQueryParams,
)

PAGE_LIMIT = 1000
MAX_PAGES = 200  # 200 pages x 1000 = 200k messages max
PAGE_DELAY_S = 0.15  # be polite to upstream between pages
MAX_RETRIES = 2  # extra attempts per page on transient failures

# Upstream uses 429 for rate limiting; 502/503/504 (and network errors,
# status_code=None) are worth one or two retries as well.
RETRYABLE_STATUS_CODES = frozenset({None, 429, 502, 503, 504})

OnPage = Callable[[int, list[FullMessage]], None]


def _is_retryable(e: HarambelogsError) -> bool:
    return e.status_code in RETRYABLE_STATUS_CODES


async def fetch_channel_logs(
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

    Returns ``(messages, truncated)``. Raises the last ``HarambelogsError``
    if a page keeps failing after retries (non-retryable errors raise
    immediately).
    """
    messages: list[FullMessage] = []
    offset = 0
    truncated = False

    for page in range(max_pages):
        params = LogQueryParams(limit=PAGE_LIMIT, offset=offset, json_=True)
        last_error: HarambelogsError | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await api.get_channel_logs(
                    channel_id_type, channel, from_date, to_date, params
                )
                last_error = None
                break
            except HarambelogsError as e:
                last_error = e
                if not _is_retryable(e) or attempt >= MAX_RETRIES:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))
        assert last_error is None  # loop breaks only on success or raise
        page_messages = resp.messages
        messages.extend(page_messages)
        if on_page is not None:
            on_page(page, page_messages)
        if len(page_messages) < PAGE_LIMIT:
            return messages, truncated
        offset += len(page_messages)
        await asyncio.sleep(PAGE_DELAY_S)

    return messages, True
