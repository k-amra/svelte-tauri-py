"""Advanced chat statistics over a channel's logs (polars-powered) - v4.2.

Execution model: full channel log fetches routinely exceed 2s, so this is
meant to run through the jobs API (POST /api/jobs), which executes it in a
worker thread with progress callbacks and shutdown interruption.

Timezone: upstream timestamps are treated as UTC; time-bucketed stats are UTC.
"""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

import polars as pl
from pydantic import BaseModel, Field

from app.services import log_cache
from app.services.emotes import fetch_channel_emotes
from app.services.harambelogs_client import HarambelogsAPI
from app.services.harambelogs_models import FullMessage
from app.services.log_fetch import fetch_channel_logs

NAME = "chat_stats"
DESCRIPTION = "Advanced polars statistics over a channel's chat logs (v4.2)."

STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "for",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "is",
        "it",
        "this",
        "that",
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "them",
        "his",
        "her",
        "its",
        "our",
        "your",
        "their",
        "me",
        "him",
        "us",
        "my",
        "mine",
        "yours",
        "was",
        "were",
        "are",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "can",
        "could",
        "should",
        "not",
        "no",
        "yes",
        "so",
        "too",
        "very",
        "just",
        "like",
        "get",
        "got",
        "im",
        "dont",
        "what",
        "when",
        "where",
        "who",
        "how",
        "why",
        "all",
        "any",
        "out",
        "te",
        "ta",
        "ten",
        "go",
        "mu",
        "sie",
        "na",
        "co",
        "jak",
        "nie",
        "ale",
        "jest",
        "bo",
        "tak",
        "ty",
        "ja",
        "po",
        "ze",
        "dla",
        "oraz",
        "lub",
        "albo",
        "czy",
        "przy",
        "bez",
        "nad",
        "pod",
        "tylko",
        "bardzo",
        "mo",
        "ju",
        "tu",
        "tam",
        "za",
        "si",
        "https",
        "http",
        "com",
        "www",
    }
)

# --- Pydantic Models ---


class Params(BaseModel):
    channel: str
    channel_id_type: Literal["channel", "channelid"] = "channel"
    from_date: datetime
    to_date: datetime

    top_n: int = Field(20, ge=5, le=100)
    top_words_n: int = Field(50, ge=10, le=200)
    top_emotes_n: int = Field(50, ge=10, le=200)
    top_phrases_n: int = Field(20, ge=0, le=50)

    include_commands: bool = True
    include_links: bool = True
    include_mentions: bool = True
    include_duplicates: bool = True
    include_phrases: bool = False
    include_sessions: bool = True
    include_concentration: bool = True
    include_message_class: bool = True

    include_new_returning: bool = True
    include_emote_pairs: bool = True
    include_engagement: bool = True
    include_anomalies: bool = True
    include_language: bool = False  # requires `langdetect` package

    session_gap_minutes: int = Field(15, ge=2, le=120)
    anomaly_sigma: float = Field(3.0, ge=1.0, le=6.0)
    force_refresh: bool = False


class TopChatterStat(BaseModel):
    user_id: str
    username: str
    messageCount: int
    activeDays: int
    firstSeen: str | None = None
    lastSeen: str | None = None
    engagement_score: float | None = None


class DayCount(BaseModel):
    date: str
    count: int


class WordCount(BaseModel):
    word: str
    count: int


class EmoteCount(BaseModel):
    name: str
    count: int


class EmotePairCount(BaseModel):
    emote1: str
    emote2: str
    count: int


class CommandCount(BaseModel):
    name: str
    count: int
    unique_users: int = 0


class DomainCount(BaseModel):
    domain: str
    count: int


class MentionCount(BaseModel):
    username: str
    count: int


class MentionPair(BaseModel):
    from_user: str
    to_user: str
    count: int


class RepeatedMessage(BaseModel):
    text: str
    count: int


class RoleCount(BaseModel):
    role: str
    messages: int
    unique_users: int


class SessionStats(BaseModel):
    total_sessions: int = 0
    avg_messages_per_session: float | None = None
    avg_session_minutes: float | None = None
    longest_session_minutes: float | None = None


class Concentration(BaseModel):
    gini_coefficient: float | None = None
    top_10pct_share: float | None = None


class MessageClassStats(BaseModel):
    questions: int = 0
    exclamations: int = 0
    all_caps: int = 0
    emote_only: int = 0
    short_messages: int = 0
    long_messages: int = 0


class PhraseCount(BaseModel):
    phrase: str
    count: int


class PlatformLinks(BaseModel):
    twitch_clips: int = 0
    youtube: int = 0
    discord: int = 0
    x_twitter: int = 0
    kick: int = 0
    other: int = 0


class PeakStat(BaseModel):
    window_start: str
    message_count: int


class ChatterDist(BaseModel):
    p50: float | None = None
    p75: float | None = None
    p90: float | None = None
    p95: float | None = None


class ActivityPerDayStats(BaseModel):
    avg_active_chatters: float | None = None
    peak_active_chatters: int | None = None


class LanguageBreakdown(BaseModel):
    language: str
    percentage: float


class AnomalyStat(BaseModel):
    window_start: str
    message_count: int
    z_score: float


class Result(BaseModel):
    total_messages: int
    unique_chatters: int
    days_spanned: int
    avg_message_length: float
    median_message_length: float | None = None
    max_message_length: int | None = None
    avg_words_per_message: float | None = None

    truncated: bool
    from_cache: bool = False
    cached_at: str | None = None

    top_chatters: list[TopChatterStat]
    activity_by_hour: list[int]
    activity_by_weekday_hour: list[list[int]]
    messages_per_day: list[DayCount]
    top_words: list[WordCount]
    top_emotes: list[EmoteCount]
    top_emote_pairs: list[EmotePairCount] = []

    messages_with_commands: int = 0
    top_commands: list[CommandCount] = []

    messages_with_links: int = 0
    top_domains: list[DomainCount] = []
    platform_links: PlatformLinks = Field(default_factory=PlatformLinks)

    messages_with_mentions: int = 0
    top_mentions: list[MentionCount] = []
    top_mention_pairs: list[MentionPair] = []

    duplicate_message_count: int = 0
    top_repeated_messages: list[RepeatedMessage] = []

    roles: list[RoleCount] = []
    sessions: SessionStats = Field(default_factory=SessionStats)
    concentration: Concentration = Field(default_factory=Concentration)
    message_classes: MessageClassStats = Field(default_factory=MessageClassStats)
    top_phrases: list[PhraseCount] = []

    top_peaks_5m: list[PeakStat] = []
    chatter_message_quantiles: ChatterDist = Field(default_factory=ChatterDist)
    activity_per_day_stats: ActivityPerDayStats = Field(default_factory=ActivityPerDayStats)

    daily_new_chatters: list[DayCount] = []
    daily_returning_chatters: list[DayCount] = []
    language_breakdown: list[LanguageBreakdown] = []
    anomalies_5m: list[AnomalyStat] = []


# --- Helpers ---


def _parse_ts(value: datetime | str) -> datetime | None:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _get_tag(tags: dict | None, key: str) -> str | None:
    if not tags:
        return None
    val = tags.get(key)
    return str(val) if val is not None else None


def _get_role(badges: str | None) -> str:
    if not badges:
        return "regular"
    # Parse badge tokens exactly (comma-separated ``name/version``).
    names: set[str] = set()
    for b in badges.split(","):
        if not b:
            continue
        names.add(b.split("/", 1)[0])
    if "broadcaster" in names:
        return "broadcaster"
    if "moderator" in names:
        return "moderator"
    if "vip" in names:
        return "vip"
    if "subscriber" in names:
        return "subscriber"
    return "regular"


def messages_to_frame(messages: list[FullMessage]) -> pl.DataFrame:
    rows: list[tuple] = []
    for m in messages:
        ts = _parse_ts(m.timestamp)
        if ts is not None:
            user_id = _get_tag(m.tags, "user-id") or m.username
            emotes_tag = _get_tag(m.tags, "emotes")
            badges = _get_tag(m.tags, "badges")
            role = _get_role(badges)
            rows.append((user_id, m.username, m.text, ts, emotes_tag, m.id, role))

    if not rows:
        return pl.DataFrame(
            {
                "user_id": pl.Series([], dtype=pl.String),
                "username": pl.Series([], dtype=pl.String),
                "text": pl.Series([], dtype=pl.String),
                "ts": pl.Series([], dtype=pl.Datetime(time_unit="us", time_zone="UTC")),
                "emotes_tag": pl.Series([], dtype=pl.String),
                "id": pl.Series([], dtype=pl.String),
                "role": pl.Series([], dtype=pl.String),
            }
        )

    user_ids, usernames, texts, stamps, emotes, ids, roles = zip(*rows, strict=True)
    return pl.DataFrame(
        {
            "user_id": list(user_ids),
            "username": list(usernames),
            "text": list(texts),
            "ts": pl.Series(list(stamps), dtype=pl.Datetime(time_unit="us", time_zone="UTC")),
            "emotes_tag": list(emotes),
            "id": list(ids),
            "role": list(roles),
        }
    ).sort("ts")


def _to_timestamp(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _extract_twitch_id(messages: list[FullMessage]) -> str | None:
    for m in messages:
        room_id = _get_tag(m.tags, "room-id")
        if room_id:
            return room_id
    return None


def _cache_meta(params: Params, df: pl.DataFrame, truncated: bool, twitch_id: str | None) -> dict:
    return {
        "channel": params.channel,
        "channel_id_type": params.channel_id_type,
        "from": params.from_date.isoformat(),
        "to": params.to_date.isoformat(),
        "fetched_at": datetime.now(UTC).timestamp(),
        "immutable": log_cache.is_immutable_range(params.from_date, params.to_date),
        "truncated": truncated,
        "message_count": df.height,
        "twitch_id": twitch_id,
    }


# --- Emote parsing (shared by _count_emotes and _compute_emote_pairs) ---


def _parse_twitch_emotes(df: pl.DataFrame) -> pl.Series:
    """Return a ``List(String)`` Series: one list of emote names per row.

    Duplicates within a message are preserved so callers can decide whether to
    count occurrences (top emotes) or unique co-occurrence (emote pairs).
    Falls back to ``[<emote_id>]`` when a range cannot be sliced from text.
    """
    if df.is_empty() or "emotes_tag" not in df.columns:
        return pl.Series("e", [], dtype=pl.List(pl.String))

    texts = df["text"].to_list()
    tags = df["emotes_tag"].to_list()
    out: list[list[str]] = []
    for tag, text in zip(tags, texts, strict=True):
        names: list[str] = []
        if tag:
            for part in str(tag).split("/"):
                if ":" not in part:
                    continue
                emote_id, _, ranges = part.partition(":")
                for occurrence in ranges.split(","):
                    name = None
                    if isinstance(text, str):
                        try:
                            start, end = occurrence.split("-")
                            name = text[int(start) : int(end) + 1] or None
                        except (ValueError, IndexError):
                            pass
                    if not name:
                        name = f"[{emote_id}]"
                    names.append(name)
        out.append(names)
    return pl.Series("e", out, dtype=pl.List(pl.String))


# --- Analytics Modules ---


def _compute_overview(df: pl.DataFrame) -> dict:
    total = df.height
    dates = df["ts"].dt.date()
    days_spanned = (dates.max() - dates.min()).days + 1 if total > 0 else 0

    length_stats = df.select(
        pl.col("text").str.len_chars().mean().alias("avg"),
        pl.col("text").str.len_chars().median().alias("med"),
        pl.col("text").str.len_chars().max().alias("max"),
    )
    avg_len = length_stats["avg"][0]
    med_len = length_stats["med"][0]
    max_len = length_stats["max"][0]

    clean_text_wpm = (
        pl.col("text").str.replace_all(r"https?://[^\s<>()\[\]{}\"',;!?]+", " ").str.replace_all(r"@[A-Za-z0-9_]+", " ")
    )
    wpm_mean = df.select(clean_text_wpm.str.extract_all(r"[A-Za-z0-9']+").list.len().alias("wc"))["wc"].mean()

    return {
        "total_messages": total,
        "unique_chatters": df["user_id"].n_unique(),
        "days_spanned": days_spanned,
        "avg_message_length": float(avg_len) if avg_len is not None else 0.0,
        "median_message_length": float(med_len) if med_len is not None else None,
        "max_message_length": int(max_len) if max_len is not None else None,
        "avg_words_per_message": float(wpm_mean) if wpm_mean is not None else None,
    }


def _compute_users(df: pl.DataFrame, top_n: int, include_engagement: bool) -> dict:
    u = df.group_by("user_id").agg(
        pl.len().alias("messageCount"),
        pl.col("username").last().alias("username"),
        pl.col("ts").min().alias("firstSeen"),
        pl.col("ts").max().alias("lastSeen"),
        pl.col("ts").dt.date().n_unique().alias("activeDays"),
        pl.col("text").str.len_chars().mean().alias("avg_msg_len"),
    )

    # Engagement score normalized against the *full* user frame so changing
    # top_n does not rescale every score.
    max_count = u["messageCount"].max()
    max_days = u["activeDays"].max()
    max_len = u["avg_msg_len"].max()

    can_score = (
        include_engagement
        and max_count is not None
        and max_count > 0
        and max_days is not None
        and max_days > 0
        and max_len is not None
        and max_len > 0
    )

    if can_score:
        u = u.with_columns(
            (
                0.5 * (pl.col("messageCount") / max_count)
                + 0.3 * (pl.col("activeDays") / max_days)
                + 0.2 * (pl.col("avg_msg_len") / max_len)
            ).alias("engagement_score")
        )
    else:
        u = u.with_columns(pl.lit(None, dtype=pl.Float64).alias("engagement_score"))

    top = u.sort("messageCount", descending=True).head(top_n)

    top_chatters = []
    for r in top.iter_rows(named=True):
        score = r["engagement_score"]
        top_chatters.append(
            {
                "user_id": r["user_id"],
                "username": r["username"],
                "messageCount": int(r["messageCount"]),
                "activeDays": int(r["activeDays"]),
                "firstSeen": r["firstSeen"].isoformat() if r["firstSeen"] else None,
                "lastSeen": r["lastSeen"].isoformat() if r["lastSeen"] else None,
                "engagement_score": round(float(score), 4) if score is not None else None,
            }
        )
    return {"top_chatters": top_chatters}


def _compute_chatter_dist(df: pl.DataFrame) -> dict:
    c = df.group_by("user_id").len()["len"]
    if c.is_empty():
        return {"chatter_message_quantiles": {}}

    qv = c.quantile([0.5, 0.75, 0.9, 0.95], interpolation="linear")
    # polars returns a plain list for multi-quantile queries
    qv = qv.to_list() if hasattr(qv, "to_list") else list(qv)
    return {
        "chatter_message_quantiles": {
            "p50": round(qv[0], 2) if len(qv) > 0 else None,
            "p75": round(qv[1], 2) if len(qv) > 1 else None,
            "p90": round(qv[2], 2) if len(qv) > 2 else None,
            "p95": round(qv[3], 2) if len(qv) > 3 else None,
        }
    }


def _compute_activity_per_day(df: pl.DataFrame) -> dict:
    if df.height == 0:
        return {"activity_per_day_stats": {}}
    active = df.group_by(pl.col("ts").dt.date()).agg(pl.col("user_id").n_unique().alias("u"))
    avg_active = active["u"].mean()
    peak_active = active["u"].max()
    return {
        "activity_per_day_stats": {
            "avg_active_chatters": float(avg_active) if avg_active is not None else None,
            "peak_active_chatters": int(peak_active) if peak_active is not None else None,
        }
    }


def _compute_time(df: pl.DataFrame) -> dict:
    hourly = [0] * 24
    for hour, count in df.group_by(pl.col("ts").dt.hour().alias("hour")).len().iter_rows():
        hourly[int(hour)] = int(count)

    heatmap = [[0] * 24 for _ in range(7)]
    for weekday, hour, count in (
        df.group_by(
            pl.col("ts").dt.weekday().alias("weekday"),
            pl.col("ts").dt.hour().alias("hour"),
        )
        .len()
        .iter_rows()
    ):
        heatmap[int(weekday) - 1][int(hour)] = int(count)

    messages_per_day = []
    if df.height > 0:
        min_date = df["ts"].min().date()
        max_date = df["ts"].max().date()
        per_day = df.group_by(df["ts"].dt.date().alias("day")).len()
        all_days = pl.date_range(min_date, max_date, interval="1d", eager=True).alias("day")
        full_days = pl.DataFrame({"day": all_days}).join(per_day, on="day", how="left").fill_null(0)
        messages_per_day = [
            {"date": day.isoformat(), "count": int(count)}
            for day, count in zip(full_days["day"].to_list(), full_days["len"].to_list(), strict=True)
        ]

    top_peaks: list[dict] = []
    if df.height >= 2:
        # Pin window semantics so Polars upgrades do not shift boundaries.
        p = (
            df.group_by_dynamic("ts", every="5m", period="5m", start_by="window", closed="left")
            .agg(pl.len())
            .sort("len", descending=True)
            .head(3)
        )
        for r in p.iter_rows(named=True):
            top_peaks.append(
                {
                    "window_start": r["ts"].isoformat(),
                    "message_count": int(r["len"]),
                }
            )

    return {
        "activity_by_hour": hourly,
        "activity_by_weekday_hour": heatmap,
        "messages_per_day": messages_per_day,
        "top_peaks_5m": top_peaks,
    }


def _count_emotes(
    df: pl.DataFrame,
    twitch_emotes: pl.Series,
    emote_map: dict[str, str],
    limit: int,
) -> tuple[list[dict], set[str]]:
    """Return (top emotes, set of all seen emote names).

    ``twitch_emotes`` is produced once by :func:`_parse_twitch_emotes` so this
    function does not re-walk the ``emotes_tag`` string.
    """
    named_counts: dict[str, int] = {}

    # Twitch emotes (from tags, already parsed).
    emote_df = pl.DataFrame({"e": twitch_emotes}).explode("e", empty_as_null=True).drop_nulls("e")
    if not emote_df.is_empty():
        counts = emote_df.group_by("e").len()
        for name, count in zip(counts["e"].to_list(), counts["len"].to_list(), strict=True):
            named_counts[str(name)] = int(count)

    # Third-party (BTTV/FFZ/7TV) tokens matched by name against the catalog.
    # Names already seen as Twitch emotes in this range are excluded to avoid
    # double counting across the two passes.
    if emote_map and "text" in df.columns:
        known_names = sorted(set(emote_map.values()) - set(named_counts))
        if known_names:
            catalog_counts = (
                df.select(pl.col("text").str.extract_all(r"[A-Za-z0-9_]+").alias("w"))
                .explode("w", empty_as_null=True)
                .drop_nulls("w")
                .filter(pl.col("w").is_in(known_names))
                .group_by("w")
                .len()
            )
            for name, count in zip(catalog_counts["w"].to_list(), catalog_counts["len"].to_list(), strict=True):
                named_counts[name] = named_counts.get(name, 0) + int(count)

    seen_names = set(named_counts.keys())
    top_emotes = sorted(named_counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [{"name": n, "count": c} for n, c in top_emotes], seen_names


def _compute_emote_pairs(twitch_emotes: pl.Series, limit: int) -> list[dict]:
    """All unique unordered emote pairs co-occurring within a single message.

    Uses a self-join on message id after exploding — one Polars pass, no
    Python per-message loops. Messages with very many distinct emotes are
    dropped to avoid O(k^2) blowups on copypasta/spam.
    """
    if len(twitch_emotes) == 0:
        return []

    edf = pl.DataFrame(
        {
            "msg_id": list(range(len(twitch_emotes))),
            "emotes": twitch_emotes,
        }
    )
    edf = edf.filter(pl.col("emotes").list.len() >= 2)
    if edf.is_empty():
        return []

    # Deduplicate within a message so "Kappa Kappa Kappa" counts as {Kappa}.
    edf = edf.with_columns(pl.col("emotes").list.unique().alias("emotes"))
    edf = edf.filter(pl.col("emotes").list.len() >= 2)
    # Cap distinct emotes per message to bound the self-join.
    edf = edf.filter(pl.col("emotes").list.len() <= 20)
    if edf.is_empty():
        return []

    exploded = edf.explode("emotes")
    pairs = (
        exploded.join(exploded, on="msg_id", suffix="_2")
        .filter(pl.col("emotes") < pl.col("emotes_2"))
        .group_by("emotes", "emotes_2")
        .len()
        .sort("len", descending=True)
        .head(limit)
    )

    return [
        {"emote1": a, "emote2": b, "count": int(c)}
        for a, b, c in zip(pairs["emotes"], pairs["emotes_2"], pairs["len"], strict=True)
    ]


def _compute_words(df: pl.DataFrame, stopwords: frozenset[str], limit: int) -> dict:
    clean_text = (
        pl.col("text")
        .str.replace_all(r"https?://[^\s<>()\[\]{}\"',;!?]+", " ")
        .str.replace_all(r"@[A-Za-z0-9_]+", " ")
        .str.to_lowercase()
    )
    words = (
        df.select(clean_text.str.extract_all(r"[a-z0-9']{2,}").alias("w"))
        .explode("w", empty_as_null=True)
        .drop_nulls("w")
        .filter(~pl.col("w").is_in(list(stopwords)))
        .group_by("w")
        .len()
        .sort("len", descending=True)
        .head(limit)
    )
    return {"top_words": [{"word": w, "count": c} for w, c in zip(words["w"], words["len"], strict=True)]}


def _compute_commands(df: pl.DataFrame, top_n: int) -> dict:
    base = (
        df.filter(pl.col("text").str.starts_with("!"))
        .select(
            pl.col("text").str.strip_prefix("!").str.extract(r"^[A-Za-z0-9_\-]+", 0).str.to_lowercase().alias("cmd"),
            "user_id",
        )
        .drop_nulls("cmd")
    )

    messages_with_commands = base.height
    top_cmds = (
        base.group_by("cmd")
        .agg(pl.len().alias("count"), pl.col("user_id").n_unique().alias("unique_users"))
        .sort("count", descending=True)
        .head(top_n)
    )
    return {
        "messages_with_commands": messages_with_commands,
        "top_commands": [
            {"name": n, "count": c, "unique_users": u}
            for n, c, u in zip(top_cmds["cmd"], top_cmds["count"], top_cmds["unique_users"], strict=True)
        ],
    }


def _compute_links(df: pl.DataFrame, top_n: int) -> dict:
    links_df = df.filter(pl.col("text").str.contains(r"https?://"))
    messages_with_links = links_df.height
    if messages_with_links == 0:
        return {
            "messages_with_links": 0,
            "top_domains": [],
            "platform_links": {
                "twitch_clips": 0,
                "youtube": 0,
                "discord": 0,
                "x_twitter": 0,
                "kick": 0,
                "other": 0,
            },
        }

    domains = (
        links_df.select(pl.col("text").str.extract_all(r"https?://[^\s<>()\[\]{}\"',;!?]+").alias("url"))
        .explode("url", empty_as_null=True)
        .drop_nulls("url")
        .select(pl.col("url").str.to_lowercase().str.extract(r"^(?:https?://)?(?:www\.)?([^/]+)", 1).alias("domain"))
        .drop_nulls("domain")
        .group_by("domain")
        .len()
        .sort("len", descending=True)
        .head(top_n)
    )

    t = links_df["text"].str.to_lowercase()
    is_clip = t.str.contains(r"clips\.twitch\.tv|twitch\.tv/\w+/clip/")
    is_yt = t.str.contains(r"youtube\.com|youtu\.be")
    is_dc = t.str.contains(r"discord\.(gg|com)")
    is_x = t.str.contains(r"x\.com|twitter\.com")
    is_kick = t.str.contains(r"kick\.com")

    any_platform = is_clip | is_yt | is_dc | is_x | is_kick

    platform_links = {
        "twitch_clips": int(is_clip.sum()),
        "youtube": int(is_yt.sum()),
        "discord": int(is_dc.sum()),
        "x_twitter": int(is_x.sum()),
        "kick": int(is_kick.sum()),
        "other": int((~any_platform).sum()),
    }
    if platform_links["other"] < 0:
        platform_links["other"] = 0

    return {
        "messages_with_links": messages_with_links,
        "top_domains": [{"domain": d, "count": c} for d, c in zip(domains["domain"], domains["len"], strict=True)],
        "platform_links": platform_links,
    }


def _compute_mentions(df: pl.DataFrame, top_n: int) -> dict:
    mentions_raw = (
        df.select(
            pl.col("username").str.to_lowercase().alias("from_user"),
            pl.col("text").str.extract_all(r"@[A-Za-z0-9_]+").alias("mentions_raw"),
        )
        .explode("mentions_raw", empty_as_null=True)
        .drop_nulls("mentions_raw")
    )

    mentions_df = mentions_raw.with_columns(
        pl.col("mentions_raw").str.slice(1).str.to_lowercase().alias("mentions")
    ).drop_nulls("mentions")

    messages_with_mentions = df.filter(pl.col("text").str.contains(r"@[A-Za-z0-9_]+")).height

    top_mens = (
        mentions_df.select(pl.col("mentions").alias("user"))
        .group_by("user")
        .len()
        .sort("len", descending=True)
        .head(top_n)
    )

    pairs = mentions_df.select(pl.col("from_user"), pl.col("mentions").alias("to_user")).filter(
        pl.col("from_user") != pl.col("to_user")
    )
    top_pairs = pairs.group_by("from_user", "to_user").len().sort("len", descending=True).head(10)

    return {
        "messages_with_mentions": messages_with_mentions,
        "top_mentions": [{"username": u, "count": c} for u, c in zip(top_mens["user"], top_mens["len"], strict=True)],
        "top_mention_pairs": [
            {"from_user": f, "to_user": t, "count": c}
            for f, t, c in zip(top_pairs["from_user"], top_pairs["to_user"], top_pairs["len"], strict=True)
        ],
    }


def _compute_health(df: pl.DataFrame, top_n: int) -> dict:
    dupes = (
        df.with_columns(pl.col("text").str.len_chars().alias("len_chars"))
        .group_by("text", "len_chars")
        .len()
        .filter(pl.col("len") > 1)
    )
    dup_sum = (dupes.select((pl.col("len") - 1).sum()).item()) if not dupes.is_empty() else 0
    duplicate_message_count = int(dup_sum or 0)

    top_reps = dupes.sort("len", descending=True).head(top_n)
    top_repeated_messages = []
    for text, count, length in zip(top_reps["text"], top_reps["len"], top_reps["len_chars"], strict=True):
        text_val = text if length <= 300 else text[:300] + "..."
        top_repeated_messages.append({"text": text_val, "count": count})

    return {
        "duplicate_message_count": duplicate_message_count,
        "top_repeated_messages": top_repeated_messages,
    }


def _compute_roles(df: pl.DataFrame) -> dict:
    roles = df.group_by("role").agg(
        pl.len().alias("messages"),
        pl.col("user_id").n_unique().alias("unique_users"),
    )
    return {
        "roles": [
            {"role": r, "messages": m, "unique_users": u}
            for r, m, u in zip(roles["role"], roles["messages"], roles["unique_users"], strict=True)
        ]
    }


def _compute_sessions(df: pl.DataFrame, gap_min: int) -> dict:
    if df.height == 0:
        return {
            "sessions": {
                "total_sessions": 0,
                "avg_messages_per_session": None,
                "avg_session_minutes": None,
                "longest_session_minutes": None,
            }
        }
    if df.height == 1:
        return {
            "sessions": {
                "total_sessions": 1,
                "avg_messages_per_session": 1.0,
                "avg_session_minutes": 0.0,
                "longest_session_minutes": 0.0,
            }
        }

    s = df.select("ts").sort("ts")
    diff = s["ts"].diff().dt.total_seconds() / 60.0
    boundary = (diff >= gap_min).fill_null(True)
    sess = boundary.cum_sum()

    agg = (
        s.with_columns(sess.alias("sid"))
        .group_by("sid")
        .agg(
            pl.len().alias("n"),
            pl.col("ts").min().alias("start"),
            pl.col("ts").max().alias("end"),
        )
        .with_columns(((pl.col("end") - pl.col("start")).dt.total_seconds() / 60.0).alias("dur_min"))
    )

    return {
        "sessions": {
            "total_sessions": agg.height,
            "avg_messages_per_session": float(agg["n"].mean()) if agg.height else None,
            "avg_session_minutes": float(agg["dur_min"].mean()) if agg.height else None,
            "longest_session_minutes": float(agg["dur_min"].max()) if agg.height else None,
        }
    }


def _compute_concentration(df: pl.DataFrame) -> dict:
    counts_list = df.group_by("user_id").len().sort("len", descending=True)["len"].to_list()
    if not counts_list:
        return {"concentration": {}}

    total = sum(counts_list)
    n = len(counts_list)
    xasc = sorted(counts_list, reverse=False)
    num = sum((2 * i - n - 1) * v for i, v in enumerate(xasc, 1))
    gini = abs(num) / (n * total) if n * total else 0.0

    k = max(1, math.ceil(n * 0.10))
    top_10_share = (sum(counts_list[:k]) / total) * 100.0 if total else 0.0

    return {
        "concentration": {
            "gini_coefficient": round(gini, 4),
            "top_10pct_share": round(top_10_share, 2),
        }
    }


def _compute_message_classes(df: pl.DataFrame) -> dict:
    txt = pl.col("text")
    r = txt.str.strip_chars_end()

    questions = int(df.filter(r.str.ends_with("?")).height)
    exclamations = int(df.filter(r.str.ends_with("!")).height)
    short_msgs = int(df.filter(txt.str.len_chars() <= 3).height)
    long_msgs = int(df.filter(txt.str.len_chars() >= 200).height)

    alpha_count = txt.str.extract_all(r"[A-Za-z]").list.len()
    upper_count = txt.str.extract_all(r"[A-Z]").list.len()
    all_caps = int(df.filter((alpha_count >= 5) & (upper_count >= (alpha_count * 0.8))).height)

    has_emote = pl.col("emotes_tag").is_not_null() & (pl.col("emotes_tag") != "")
    vis_words = (
        txt.str.replace_all(r"https?://\S+", " ")
        .str.replace_all(r"@\w+", " ")
        .str.extract_all(r"[A-Za-z]{2,}")
        .list.len()
    )
    emote_only = int(df.filter(has_emote & (vis_words == 0)).height)

    return {
        "message_classes": {
            "questions": questions,
            "exclamations": exclamations,
            "all_caps": all_caps,
            "emote_only": emote_only,
            "short_messages": short_msgs,
            "long_messages": long_msgs,
        }
    }


def _compute_phrases(df: pl.DataFrame, limit: int) -> dict:
    clean_text = (
        pl.col("text")
        .str.replace_all(r"https?://[^\s<>()\[\]{}\"',;!?]+", " ")
        .str.replace_all(r"@[A-Za-z0-9_]+", " ")
        .str.to_lowercase()
    )
    tokens_df = df.select(clean_text.str.extract_all(r"[a-z0-9']{2,}").alias("t")).filter(pl.col("t").list.len() >= 2)

    bigrams = (
        tokens_df.with_columns(
            pl.col("t").list.slice(0, pl.col("t").list.len() - 1).alias("a"),
            pl.col("t").list.slice(1).alias("b"),
        )
        .explode(["a", "b"])
        .drop_nulls(["a", "b"])
        .select((pl.col("a") + " " + pl.col("b")).alias("phrase"))
        .group_by("phrase")
        .len()
        .filter(pl.col("len") >= 2)
        .sort("len", descending=True)
        .head(limit)
    )

    return {"top_phrases": [{"phrase": p, "count": c} for p, c in zip(bigrams["phrase"], bigrams["len"], strict=True)]}


def _compute_new_returning(df: pl.DataFrame) -> dict:
    """Daily counts of new vs returning chatters within the requested range.

    A user is "new" on the day of their first message in the range, and
    "returning" on any later day they appear in.
    """
    if df.height == 0:
        return {"daily_new_chatters": [], "daily_returning_chatters": []}

    first_seen = df.group_by("user_id").agg(pl.col("ts").min().dt.date().alias("first_day"))
    daily_users = df.select(["ts", "user_id"]).with_columns(pl.col("ts").dt.date().alias("day"))
    merged = daily_users.join(first_seen, on="user_id", how="left")

    new_counts = (
        merged.filter(pl.col("day") == pl.col("first_day")).group_by("day").agg(pl.col("user_id").n_unique().alias("n"))
    )
    returning_counts = (
        merged.filter(pl.col("day") > pl.col("first_day")).group_by("day").agg(pl.col("user_id").n_unique().alias("n"))
    )

    min_day = df["ts"].min().date()
    max_day = df["ts"].max().date()
    all_days = pl.date_range(min_day, max_day, interval="1d", eager=True).alias("day")
    all_days_df = pl.DataFrame({"day": all_days})

    new_full = all_days_df.join(new_counts, on="day", how="left").fill_null(0)
    returning_full = all_days_df.join(returning_counts, on="day", how="left").fill_null(0)

    daily_new = [
        {"date": d.isoformat(), "count": int(c)}
        for d, c in zip(new_full["day"].to_list(), new_full["n"].to_list(), strict=True)
    ]
    daily_returning = [
        {"date": d.isoformat(), "count": int(c)}
        for d, c in zip(returning_full["day"].to_list(), returning_full["n"].to_list(), strict=True)
    ]

    return {"daily_new_chatters": daily_new, "daily_returning_chatters": daily_returning}


def _detect_anomalies(df: pl.DataFrame, sigma: float) -> list[dict]:
    if df.height < 10:
        return []

    binned = df.group_by_dynamic("ts", every="5m", period="5m", start_by="window", closed="left").agg(pl.len()).sort("ts")
    if binned.height < 10:
        return []

    counts = binned["len"]
    mean = counts.mean()
    std = counts.std()
    if mean is None or std is None or std == 0:
        return []

    binned = binned.with_columns(((counts - mean) / std).alias("z_score"))
    anomalies = binned.filter(pl.col("z_score").abs() >= sigma)

    return [
        {
            "window_start": r["ts"].isoformat(),
            "message_count": int(r["len"]),
            "z_score": round(float(r["z_score"]), 2),
        }
        for r in anomalies.iter_rows(named=True)
    ]


_LANGDETECT_SEEDED = False


def _detect_language(df: pl.DataFrame) -> list[dict]:
    """Optional basic language breakdown. Requires the ``langdetect`` package."""
    global _LANGDETECT_SEEDED
    try:
        from langdetect import DetectorFactory, detect  # type: ignore
        from langdetect.lang_detect_exception import LangDetectException  # type: ignore
    except ImportError:
        return []

    if not _LANGDETECT_SEEDED:
        DetectorFactory.seed = 0
        _LANGDETECT_SEEDED = True

    cleaned = pl.col("text").str.replace_all(r"https?://\S+", " ").str.replace_all(r"@[A-Za-z0-9_]+", " ")
    # Keep messages with a meaningful amount of alphabetic content so the
    # detector is not dominated by emote spam / "Kappa Kappa Kappa".
    candidates = (
        df.select(cleaned.alias("c"))
        .filter(pl.col("c").str.extract_all(r"[A-Za-z]").list.len() >= 10)
        .get_column("c")
        .to_list()
    )
    if not candidates:
        return []

    rng = random.Random(42)
    sample_size = min(1000, len(candidates))
    sample = rng.sample(candidates, sample_size)

    lang_counts: dict[str, int] = {}
    for text in sample:
        try:
            lang = detect(text)
        except LangDetectException:
            continue
        except Exception:
            continue
        lang_counts[lang] = lang_counts.get(lang, 0) + 1

    total = sum(lang_counts.values())
    if total == 0:
        return []

    return [
        {"language": lang, "percentage": round((count / total) * 100, 2)}
        for lang, count in sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)
    ]


# --- Orchestrator ---


def compute_stats(df: pl.DataFrame, params: Params, emote_map: dict[str, str]) -> dict:
    if df.is_empty():
        return {
            "total_messages": 0,
            "unique_chatters": 0,
            "days_spanned": 0,
            "avg_message_length": 0.0,
            "median_message_length": None,
            "max_message_length": None,
            "avg_words_per_message": None,
            "top_chatters": [],
            "activity_by_hour": [0] * 24,
            "activity_by_weekday_hour": [[0] * 24 for _ in range(7)],
            "messages_per_day": [],
            "top_words": [],
            "top_emotes": [],
            "top_emote_pairs": [],
            "roles": [],
            "top_peaks_5m": [],
            "messages_with_commands": 0,
            "top_commands": [],
            "messages_with_links": 0,
            "top_domains": [],
            "platform_links": {
                "twitch_clips": 0,
                "youtube": 0,
                "discord": 0,
                "x_twitter": 0,
                "kick": 0,
                "other": 0,
            },
            "messages_with_mentions": 0,
            "top_mentions": [],
            "top_mention_pairs": [],
            "duplicate_message_count": 0,
            "top_repeated_messages": [],
            "sessions": {
                "total_sessions": 0,
                "avg_messages_per_session": None,
                "avg_session_minutes": None,
                "longest_session_minutes": None,
            },
            "concentration": {},
            "message_classes": {
                "questions": 0,
                "exclamations": 0,
                "all_caps": 0,
                "emote_only": 0,
                "short_messages": 0,
                "long_messages": 0,
            },
            "top_phrases": [],
            "chatter_message_quantiles": {},
            "activity_per_day_stats": {},
            "daily_new_chatters": [],
            "daily_returning_chatters": [],
            "language_breakdown": [],
            "anomalies_5m": [],
        }

    # Parse emotes once; both top emotes and co-occurrence pairs use this.
    twitch_emotes = _parse_twitch_emotes(df)

    stats: dict = {}
    stats.update(_compute_overview(df))
    stats.update(_compute_users(df, params.top_n, params.include_engagement))
    stats.update(_compute_chatter_dist(df))
    stats.update(_compute_activity_per_day(df))
    stats.update(_compute_time(df))
    stats.update(_compute_roles(df))

    top_emotes, seen_emotes = _count_emotes(df, twitch_emotes, emote_map, params.top_emotes_n)
    stats["top_emotes"] = top_emotes

    if params.include_emote_pairs:
        stats["top_emote_pairs"] = _compute_emote_pairs(twitch_emotes, params.top_n)

    stopwords = STOPWORDS | {name.lower() for name in seen_emotes}
    stats.update(_compute_words(df, stopwords, params.top_words_n))

    if params.include_commands:
        stats.update(_compute_commands(df, params.top_n))
    if params.include_links:
        stats.update(_compute_links(df, params.top_n))
    if params.include_mentions:
        stats.update(_compute_mentions(df, params.top_n))
    if params.include_duplicates:
        stats.update(_compute_health(df, params.top_n))
    if params.include_sessions:
        stats.update(_compute_sessions(df, params.session_gap_minutes))
    if params.include_concentration:
        stats.update(_compute_concentration(df))
    if params.include_message_class:
        stats.update(_compute_message_classes(df))
    if params.include_phrases:
        stats.update(_compute_phrases(df, params.top_phrases_n))
    if params.include_new_returning:
        stats.update(_compute_new_returning(df))
    if params.include_anomalies:
        stats["anomalies_5m"] = _detect_anomalies(df, params.anomaly_sigma)
    if params.include_language:
        stats["language_breakdown"] = _detect_language(df)

    return stats


# --- Execution & Caching ---


async def _fetch_all(params: Params, progress: Callable[[float, str], None]) -> tuple[list[FullMessage], bool]:
    total = 0

    def on_page(page: int, page_messages: list[FullMessage]) -> None:
        nonlocal total
        total += len(page_messages)
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


def _build_stats(df: pl.DataFrame, emote_map: dict[str, str], params: Params) -> dict:
    return compute_stats(df, params, emote_map)


async def _safe_fetch_emotes(channel: str, twitch_id: str | None) -> dict[str, str]:
    try:
        return await fetch_channel_emotes(channel, twitch_id)
    except Exception:
        return {}


def _run_fresh(params: Params, fp: str, progress: Callable[[float, str], None]) -> Result:
    progress(2.0, "connecting")
    messages, truncated = asyncio.run(_fetch_all(params, progress))

    progress(80.0, "fetching emotes")
    twitch_id = _extract_twitch_id(messages)
    emote_map = asyncio.run(_safe_fetch_emotes(params.channel, twitch_id))

    progress(85.0, "building dataframe & computing stats")
    df = messages_to_frame(messages)
    log_cache.save(fp, df, _cache_meta(params, df, truncated, twitch_id))

    stats = _build_stats(df, emote_map, params)
    stats["truncated"] = truncated
    progress(100.0, "done")
    return Result(**stats)


def _run_top_up(
    params: Params, fp: str, stale: tuple[pl.DataFrame, dict], progress: Callable[[float, str], None]
) -> Result:
    old_df, old_meta = stale
    fetched_at = float(old_meta.get("fetched_at", 0.0))
    since = datetime.fromtimestamp(fetched_at, UTC) - timedelta(minutes=10)
    if since < params.from_date:
        since = params.from_date

    to_ts = _to_timestamp(params.to_date)
    if to_ts is not None and fetched_at >= to_ts:
        progress(80.0, f"cache hit: {old_df.height} messages")
        twitch_id = old_meta.get("twitch_id")
        emote_map = asyncio.run(_safe_fetch_emotes(params.channel, twitch_id))
        stats = _build_stats(old_df, emote_map, params)
        stats["truncated"] = bool(old_meta.get("truncated", False))
        stats["from_cache"] = True
        stats["cached_at"] = datetime.fromtimestamp(fetched_at, UTC).isoformat()
        progress(100.0, "done (cached)")
        return Result(**stats)

    progress(2.0, f"updating cache since {since.isoformat()}")
    delta_params = params.model_copy(update={"from_date": since})
    messages, delta_truncated = asyncio.run(_fetch_all(delta_params, progress))

    progress(82.0, "merging with cache")
    new_df = messages_to_frame(messages)
    if "id" in old_df.columns:
        df = pl.concat([old_df, new_df], how="vertical").unique(subset=["id"], keep="last", maintain_order=True)
    else:
        df = pl.concat([old_df, new_df], how="diagonal")
    df = df.sort("ts")

    twitch_id = old_meta.get("twitch_id") or _extract_twitch_id(messages)
    emote_map = asyncio.run(_safe_fetch_emotes(params.channel, twitch_id))
    is_truncated = bool(old_meta.get("truncated", False)) or delta_truncated
    log_cache.save(fp, df, _cache_meta(params, df, is_truncated, twitch_id))

    progress(85.0, "computing stats")
    stats = _build_stats(df, emote_map, params)
    stats["truncated"] = is_truncated
    progress(100.0, "done")
    return Result(**stats)


def run(params: Params, progress: Callable[[float, str], None] = lambda pct, msg="": None) -> Result:
    start_ts = _to_timestamp(params.from_date)
    end_ts = _to_timestamp(params.to_date)
    if start_ts is not None and end_ts is not None and start_ts >= end_ts:
        raise ValueError("from_date must be before to_date")

    fp = log_cache.fingerprint(params.channel_id_type, params.channel, params.from_date, params.to_date)

    if not params.force_refresh:
        cached = log_cache.load(fp)
        if cached is not None:
            df, meta = cached
            progress(80.0, f"cache hit: {meta.get('message_count', df.height)} messages")
            twitch_id = meta.get("twitch_id")
            emote_map = asyncio.run(_safe_fetch_emotes(params.channel, twitch_id))

            stats = _build_stats(df, emote_map, params)
            stats["truncated"] = bool(meta.get("truncated", False))
            stats["from_cache"] = True
            fetched_at = meta.get("fetched_at")
            stats["cached_at"] = datetime.fromtimestamp(fetched_at, UTC).isoformat() if fetched_at else None
            progress(100.0, "done (cached)")
            return Result(**stats)

        stale = log_cache.load(fp, allow_stale=True)
        if stale is not None:
            return _run_top_up(params, fp, stale, progress)

    return _run_fresh(params, fp, progress)
