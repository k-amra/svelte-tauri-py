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
from app.services.emotes import fetch_channel_emotes
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


class EmoteCount(BaseModel):
    name: str
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
    top_emotes: list[EmoteCount]


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
    """Convert fetched messages to a polars frame (username/text/ts/emotes_tag).

    The raw `emotes` IRC tag is preserved so emote counting keeps working
    on frames loaded back from the parquet disk cache. Rows with unparsable
    timestamps are dropped — they cannot be placed in time, and every
    downstream stat is time-based.
    """
    rows: list[tuple[str, str, datetime, str | None]] = []
    for m in messages:
        ts = _parse_ts(m.timestamp)
        if ts is not None:
            emotes_tag = m.tags.get("emotes") if m.tags else None
            rows.append((m.username, m.text, ts, str(emotes_tag) if emotes_tag else None))
    if not rows:
        return pl.DataFrame(
            {
                "username": pl.Series([], dtype=pl.String),
                "text": pl.Series([], dtype=pl.String),
                "ts": pl.Series([], dtype=pl.Datetime(time_unit="us", time_zone="UTC")),
                "emotes_tag": pl.Series([], dtype=pl.String),
            }
        )
    usernames, texts, stamps, emotes = zip(*rows, strict=True)
    return pl.DataFrame(
        {
            "username": list(usernames),
            "text": list(texts),
            "ts": pl.Series(list(stamps), dtype=pl.Datetime(time_unit="us", time_zone="UTC")),
            "emotes_tag": list(emotes),
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
        "top_emotes": [],
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


def _count_emotes_from_frame(df: pl.DataFrame, emote_map: dict[str, str]) -> list[dict]:
    """Count emotes from the frame's preserved IRC tags (100% accurate).

    The native Twitch `emotes` tag (`id:start-end,start-end`) carries
    character ranges into the message text, so the emote *name* is read
    straight from the message — no id→name API needed. This matters because
    the tag only covers Twitch-native emotes, while the 7TV/BTTV/FFZ map
    covers third-party ones: the two id spaces barely overlap. Third-party
    emotes (absent from the tag) are matched as whole words in the text
    against the known catalog names, excluding names already seen via tags
    so nothing is double-counted.
    """
    if "emotes_tag" not in df.columns:
        return []

    texts = df["text"].to_list() if "text" in df.columns else [None] * df.height
    named_counts: dict[str, int] = {}
    for tag, text in zip(df["emotes_tag"].to_list(), texts, strict=True):
        if not tag:
            continue
        for part in str(tag).split("/"):
            if ":" not in part:
                continue
            emote_id, _, ranges = part.partition(":")
            for occurrence in ranges.split(","):
                name: str | None = None
                if isinstance(text, str):
                    try:
                        start, end = occurrence.split("-")
                        name = text[int(start) : int(end) + 1] or None
                    except (ValueError, IndexError):
                        name = None
                if not name:
                    name = f"[{emote_id}]"
                named_counts[name] = named_counts.get(name, 0) + 1

    # Third-party emotes never appear in the IRC tag: match catalog names.
    if emote_map and "text" in df.columns:
        known_names = set(emote_map.values()) - set(named_counts)
        if known_names:
            for text in df["text"].to_list():
                for word in str(text).split():
                    if word in known_names:
                        named_counts[word] = named_counts.get(word, 0) + 1

    top_emotes = sorted(named_counts.items(), key=lambda item: item[1], reverse=True)[:TOP_WORDS]
    return [{"name": name, "count": count} for name, count in top_emotes]


async def _fetch_all(
    params: Params, progress: Callable[[float, str], None]
) -> tuple[list[FullMessage], bool]:
    """Fetch every page; map page index onto the 2% → 78% progress budget."""
    total = 0

    def on_page(page: int, page_messages: list[FullMessage]) -> None:
        nonlocal total
        total += len(page_messages)
        # Diminishing approach to 78%: keeps moving on very long fetches.
        pct = 2.0 + 76.0 * (1.0 - 0.9 ** (page + 1))
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

        # Emote catalog is tiny and cached 24h separately — refresh it even
        # on a frame cache hit, using the stored Twitch user id.
        twitch_id = meta.get("twitch_id")
        emote_map = asyncio.run(fetch_channel_emotes(params.channel, twitch_id))

        stats = compute_stats(df, params.top_n)
        stats["top_emotes"] = _count_emotes_from_frame(df, emote_map)
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

    progress(80.0, "fetching emotes")
    twitch_id = None
    for m in messages:
        if m.tags and "room-id" in m.tags:
            twitch_id = str(m.tags["room-id"])
            break

    emote_map = asyncio.run(fetch_channel_emotes(params.channel, twitch_id))

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
            "twitch_id": twitch_id,
        },
    )
    stats = compute_stats(df, params.top_n)
    stats["top_emotes"] = _count_emotes_from_frame(df, emote_map)
    stats["truncated"] = truncated
    progress(100.0, "done")
    return Result(**stats)
