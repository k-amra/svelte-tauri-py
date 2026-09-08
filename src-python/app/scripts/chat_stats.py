"""Advanced chat statistics over a channel's logs (polars-powered).

Contract (see plan.md §4 + AGENTS.md):
- Pydantic `Params` and `Result` models
- `NAME`, `DESCRIPTION` strings
- `run(params: Params, progress=...) -> Result`

Execution model: this script fetches full channel logs (routinely >2s), so it
is meant to run through the jobs API (`POST /api/jobs`), which executes it in
a worker thread with progress callbacks and shutdown interruption.

Timezone: upstream timestamps are treated as UTC; the heatmap is labelled UTC.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

import polars as pl
from pydantic import BaseModel, Field

from app.services import log_cache
from app.services.harambelogs_client import HarambelogsAPI
from app.services.harambelogs_models import FullMessage
from app.services.log_fetch import fetch_channel_logs

NAME = "chat_stats"
DESCRIPTION = "Advanced polars statistics over a channel's chat logs."

TOP_WORDS = 50

STOPWORDS = frozenset(
    {
        # English
        "the", "a", "an", "and", "or", "but", "if", "then", "else", "for",
        "to", "of", "in", "on", "at", "by", "with", "from", "as", "is",
        "it", "this", "that", "these", "those", "i", "you", "he", "she",
        "we", "they", "them", "his", "her", "its", "our", "your", "their",
        "me", "him", "us", "my", "mine", "yours", "was", "were", "are",
        "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "can", "could", "should", "not", "no", "yes",
        "so", "too", "very", "just", "like", "get", "got", "im", "dont",
        "what", "when", "where", "who", "how", "why", "all", "any", "out",
        # Polish (harambelogs.pl chats; ASCII forms + fragments left behind
        # by the [a-z0-9'] tokenizer splitting diacritics, e.g. "też"→"te")
        "te", "ta", "ten", "go", "mu", "sie", "na", "co", "jak",
        "nie", "ale", "jest", "bo", "tak", "ty", "ja", "po", "ze", "dla",
        "oraz", "lub", "albo", "czy", "przy", "bez", "nad", "pod", "tylko",
        "bardzo", "mo", "ju", "tu", "tam",
        # URL noise
        "https", "http", "com", "www",
    }
)


class Params(BaseModel):
    channel: str
    channel_id_type: Literal["channel", "channelid"] = "channel"
    from_date: datetime | None = None
    to_date: datetime | None = None
    top_n: int = Field(20, ge=5, le=100)
    force_refresh: bool = False  # bypass the cache and re-download


class TopChatterStat(BaseModel):
    username: str
    messageCount: int


class DayCount(BaseModel):
    date: str
    count: int


class WordCount(BaseModel):
    word: str
    count: int


class Result(BaseModel):
    total_messages: int
    unique_chatters: int
    days_spanned: int
    avg_message_length: float
    truncated: bool
    from_cache: bool = False
    cached_at: str | None = None  # ISO time of the original fetch (string: SSE-safe)
    top_chatters: list[TopChatterStat]
    activity_by_hour: list[int]  # len 24, UTC
    activity_by_weekday_hour: list[list[int]]  # 7 x 24, Monday-first, UTC
    messages_per_day: list[DayCount]
    top_words: list[WordCount]


def _parse_ts(value: datetime | str) -> datetime | None:
    """Parse one timestamp to UTC-aware datetime; None when unparsable."""
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def messages_to_frame(messages: list[FullMessage]) -> pl.DataFrame:
    """Convert fetched messages to a polars frame (username/text/ts).

    Rows with unparsable timestamps are dropped — they cannot be placed
    in time, and every downstream stat is time-based.
    """
    rows: list[tuple[str, str, datetime]] = []
    for m in messages:
        ts = _parse_ts(m.timestamp)
        if ts is not None:
            rows.append((m.username, m.text, ts))
    if not rows:
        return pl.DataFrame(
            {
                "username": pl.Series([], dtype=pl.String),
                "text": pl.Series([], dtype=pl.String),
                "ts": pl.Series([], dtype=pl.Datetime(time_unit="us", time_zone="UTC")),
            }
        )
    usernames, texts, stamps = zip(*rows, strict=True)
    return pl.DataFrame(
        {
            "username": list(usernames),
            "text": list(texts),
            "ts": pl.Series(list(stamps), dtype=pl.Datetime(time_unit="us", time_zone="UTC")),
        }
    )


def _empty_stats() -> dict:
    return {
        "total_messages": 0,
        "unique_chatters": 0,
        "days_spanned": 0,
        "avg_message_length": 0.0,
        "truncated": False,
        "top_chatters": [],
        "activity_by_hour": [0] * 24,
        "activity_by_weekday_hour": [[0] * 24 for _ in range(7)],
        "messages_per_day": [],
        "top_words": [],
    }


def compute_stats(df: pl.DataFrame, top_n: int) -> dict:
    """Pure analytics layer: frame in, JSON-serializable stats out.

    No network, no progress — fully unit-testable. All lists are capped
    (`top_n`, 50 words) so the result stays small enough to ride through
    job polling/SSE.
    """
    if df.is_empty():
        return _empty_stats()

    total = df.height
    dates = df["ts"].dt.date()
    days_spanned = (dates.max() - dates.min()).days + 1

    top = (
        df.group_by("username")
        .len()
        .sort("len", descending=True)
        .head(top_n)
    )
    top_chatters = [
        {"username": name, "messageCount": count}
        for name, count in zip(top["username"].to_list(), top["len"].to_list(), strict=True)
    ]

    hourly = [0] * 24
    for hour, count in (
        df.group_by(pl.col("ts").dt.hour().alias("hour"))
        .len()
        .iter_rows()
    ):
        hourly[int(hour)] = int(count)

    heatmap = [[0] * 24 for _ in range(7)]
    for weekday, hour, count in (
        df.group_by(
            pl.col("ts").dt.weekday().alias("weekday"),  # ISO: Monday=1..Sunday=7
            pl.col("ts").dt.hour().alias("hour"),
        )
        .len()
        .iter_rows()
    ):
        heatmap[int(weekday) - 1][int(hour)] = int(count)

    per_day = (
        df.group_by(dates.alias("day"))
        .len()
        .sort("day")
    )
    messages_per_day = [
        {"date": day.isoformat(), "count": int(count)}
        for day, count in zip(per_day["day"].to_list(), per_day["len"].to_list(), strict=True)
    ]

    words = (
        df.select(
            pl.col("text")
            .str.to_lowercase()
            .str.extract_all(r"[a-z0-9']{2,}")
            .alias("w")
        )
        .explode("w", empty_as_null=True)
        .drop_nulls("w")
        .filter(~pl.col("w").is_in(STOPWORDS))
        .group_by("w")
        .len()
        .sort("len", descending=True)
        .head(TOP_WORDS)
    )
    top_words = [
        {"word": word, "count": int(count)}
        for word, count in zip(words["w"].to_list(), words["len"].to_list(), strict=True)
    ]

    avg_len = df["text"].str.len_chars().mean()
    return {
        "total_messages": total,
        "unique_chatters": df["username"].n_unique(),
        "days_spanned": days_spanned,
        "avg_message_length": float(avg_len) if avg_len is not None else 0.0,
        "truncated": False,
        "top_chatters": top_chatters,
        "activity_by_hour": hourly,
        "activity_by_weekday_hour": heatmap,
        "messages_per_day": messages_per_day,
        "top_words": top_words,
    }


async def _fetch_all(
    params: Params, progress: Callable[[float, str], None]
) -> tuple[list[FullMessage], bool]:
    """Fetch every page; map page index onto the 2% → 80% progress budget."""
    total = 0

    def on_page(page: int, page_messages: list[FullMessage]) -> None:
        nonlocal total
        total += len(page_messages)
        # Diminishing approach to 80%: keeps moving on very long fetches.
        pct = 2.0 + 78.0 * (1.0 - 0.9 ** (page + 1))
        progress(pct, f"fetched {total} messages (page {page + 1})")

    async with HarambelogsAPI() as api:
        return await fetch_channel_logs(
            api,
            params.channel_id_type,
            params.channel,
            params.from_date,
            params.to_date,
            on_page=on_page,
        )


def run(
    params: Params, progress: Callable[[float, str], None] = lambda pct, msg="": None
) -> Result:
    fp = log_cache.fingerprint(params.channel_id_type, params.channel, params.from_date, params.to_date)

    cached = None if params.force_refresh else log_cache.load(fp)
    if cached is not None:
        df, meta = cached
        progress(80.0, f"cache hit: {meta.get('message_count', df.height)} messages")
        stats = compute_stats(df, params.top_n)
        stats["truncated"] = bool(meta.get("truncated", False))
        stats["from_cache"] = True
        fetched_at = meta.get("fetched_at")
        stats["cached_at"] = datetime.fromtimestamp(fetched_at, UTC).isoformat() if fetched_at else None
        progress(100.0, "done (cached)")
        return Result(**stats)

    progress(2.0, "connecting")
    # Scripts run in worker threads (jobs API / FastAPI threadpool), so
    # bridging the async fetcher with asyncio.run() is safe here.
    messages, truncated = asyncio.run(_fetch_all(params, progress))
    progress(82.0, "building dataframe")
    df = messages_to_frame(messages)
    log_cache.save(
        fp,
        df,
        {
            "channel": params.channel,
            "channel_id_type": params.channel_id_type,
            "from": params.from_date.isoformat() if params.from_date else None,
            "to": params.to_date.isoformat() if params.to_date else None,
            "fetched_at": datetime.now(UTC).timestamp(),
            "immutable": log_cache.is_immutable_range(params.from_date, params.to_date),
            "truncated": truncated,
            "message_count": df.height,
        },
    )
    stats = compute_stats(df, params.top_n)
    stats["truncated"] = truncated
    progress(100.0, "done")
    return Result(**stats)
