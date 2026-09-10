"""Advanced chat statistics over a channel's logs (polars-powered) - v4.5.

Execution model: full channel log fetches routinely exceed 2s, so this is
meant to run through the jobs API (POST /api/jobs), which executes it in a
worker thread with progress callbacks and shutdown interruption.

Timezone: upstream timestamps are treated as UTC; time-bucketed stats are UTC.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import polars as pl
from pydantic import BaseModel, Field, model_validator

from app.services import log_cache
from app.services.emotes import fetch_channel_emotes
from app.services.harambelogs_client import HarambelogsAPI, HarambelogsError
from app.services.harambelogs_models import FullMessage
from app.services.log_fetch import RETRYABLE_STATUS_CODES, channel_log_days, fetch_channel_logs

logger = logging.getLogger(__name__)

NAME = "chat_stats"
DESCRIPTION = "Advanced polars statistics over a channel's chat logs (v4.5)."

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
        # --- Polish ---
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
        # --- Web ---
        "https",
        "http",
        "com",
        "www",
    }
)

# --- Regex Constants ---
# URL_RE is intentionally conservative: it truncates on ')' for Wikipedia-style
# URLs. That's an acceptable tradeoff — fixing it requires paren-balancing.
URL_RE = r"https?://[^\s<>()\[\]{}\"',;!?]+"

# NOTE: Polars' Rust regex engine does not support look-around (neither
# look-ahead `(?=...)`/`(?!...)` nor look-behind `(?<=...)`/`(?<!...)`). All
# patterns below are look-around-free. `\B` (non-word-boundary) is used to
# reject the `@` inside emails/URLs without a look-behind.
#
# Twitch usernames are ASCII (letters, digits, underscore). `\B@` means:
# match `@` where the preceding char is NOT a word character — equivalent
# to the old `(?<![A-Za-z0-9_])@`, but supported by Polars.
MENTION_RE = r"\B@[A-Za-z0-9_]+"

# Words: Unicode-aware, applied after .str.to_lowercase(). First char must be
# a letter or digit (replaces the old `(?=[\p{L}\p{N}])` look-ahead);
# remaining chars may also include apostrophes, so `don't` and `a'b` match
# but `'''` does not.
WORD_RE = r"[\p{L}\p{N}][\p{L}\p{N}']+"

# Emote names (Twitch, BTTV, FFZ, 7TV) are ASCII identifiers.
EMOTE_TOKEN_RE = r"[A-Za-z0-9_]+"
# Command names are ASCII identifiers.
COMMAND_RE = r"^[A-Za-z0-9_\-]+"


def _clean_text_expr(*, lowercase: bool = True) -> pl.Expr:
    """URL/mention-stripped text expression, shared by word/phrase/language passes.

    Args:
        lowercase: apply `.str.to_lowercase()`. `_detect_language` wants
            original case preserved so the detector sees real casing.
    """
    expr = pl.col("text").str.replace_all(URL_RE, " ").str.replace_all(MENTION_RE, " ")
    return expr.str.to_lowercase() if lowercase else expr

# --- Magic Numbers ---
PROGRESS_MSG_THRESHOLD = 2000
MAX_REPEAT_TEXT_LEN = 300
MAX_EMOTES_PER_MSG = 20
MIN_ALPHA_CHARS_FOR_LANG = 10
LANG_SAMPLE_SIZE = 1000
MIN_ALPHA_FOR_CAPS = 5
MAX_ANOMALIES = 50

# --- Pydantic Models ---


class Params(BaseModel):
    channel: str
    channel_id_type: Literal["channel", "channelid"] = "channel"
    from_date: datetime
    # NOTE: to_date is EXCLUSIVE — see _slice_range / _get_months_range.
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
    include_language: bool = False

    session_gap_minutes: int = Field(15, ge=2, le=120)
    anomaly_sigma: float = Field(3.0, ge=1.0, le=6.0)
    force_refresh: bool = False

    # Hard ceiling on the requested range. Beyond this the per-day arrays
    # (messages_per_day, daily_new_chatters, daily_returning_chatters) each
    # hold one entry per calendar day and would bloat the job result
    # payload. 366 * 3 ≈ 1100 entries worst case. Raise explicitly if the
    # payload size is acceptable.
    max_range_days: int = Field(366, ge=1, le=3660)

    @model_validator(mode="after")
    def _validate_date_order(self) -> Params:
        if self.from_date >= self.to_date:
            raise ValueError("from_date must be before to_date")
        span = (self.to_date - self.from_date).days
        if span > self.max_range_days:
            raise ValueError(
                f"requested range is {span} days; max is {self.max_range_days}. "
                "Raise max_range_days explicitly if the payload size is acceptable."
            )
        return self


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
        if isinstance(value, str):
            # Python <=3.10 fromisoformat doesn't support the 'Z' suffix;
            # without this normalization every message would be silently
            # dropped on 3.10 (empty result, no error).
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            dt = datetime.fromisoformat(value)
        else:
            dt = value
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
    user_ids: list[str] = []
    usernames: list[str] = []
    texts: list[str] = []
    stamps: list[datetime] = []
    emotes: list[str | None] = []
    ids: list[str | None] = []
    roles: list[str] = []

    for m in messages:
        ts = _parse_ts(m.timestamp)
        if ts is None:
            continue
        user_ids.append(_get_tag(m.tags, "user-id") or m.username)
        usernames.append(m.username)
        texts.append(m.text)
        stamps.append(ts)
        emotes.append(_get_tag(m.tags, "emotes"))
        ids.append(m.id)
        roles.append(_get_role(_get_tag(m.tags, "badges")))

    if not stamps:
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

    return pl.DataFrame(
        {
            # Pinned dtypes (not inferred): an all-None column would infer
            # Null and then fail to vstack with parquet-loaded String frames.
            "user_id": pl.Series(user_ids, dtype=pl.String),
            "username": pl.Series(usernames, dtype=pl.String),
            "text": pl.Series(texts, dtype=pl.String),
            "ts": pl.Series(stamps, dtype=pl.Datetime(time_unit="us", time_zone="UTC")),
            "emotes_tag": pl.Series(emotes, dtype=pl.String),
            "id": pl.Series(ids, dtype=pl.String),
            "role": pl.Series(roles, dtype=pl.String),
        }
    ).sort("ts")


def _dedupe_by_id(df: pl.DataFrame) -> pl.DataFrame:
    """Dedupe by message id, keeping the last occurrence.

    Null-id rows are kept as distinct rows (not collapsed), so a message
    whose upstream id is missing cannot silently delete other null-id
    messages. In practice this only matters at month boundaries and in
    historical data.
    """
    if df.is_empty() or "id" not in df.columns:
        return df
    non_null = df.filter(pl.col("id").is_not_null())
    null_part = df.filter(pl.col("id").is_null())
    if not non_null.is_empty():
        non_null = non_null.unique(subset=["id"], keep="last", maintain_order=True)
    if null_part.is_empty():
        return non_null
    return pl.concat([non_null, null_part], how="vertical")


def _extract_twitch_id(messages: list[FullMessage]) -> str | None:
    for m in messages:
        room_id = _get_tag(m.tags, "room-id")
        if room_id:
            return room_id
    return None


# --- Emote parsing ---


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
    days_spanned = max(1, (dates.max() - dates.min()).days + 1) if total > 0 else 0

    length_stats = df.select(
        pl.col("text").str.len_chars().mean().alias("avg"),
        pl.col("text").str.len_chars().median().alias("med"),
        pl.col("text").str.len_chars().max().alias("max"),
    )
    avg_len = length_stats["avg"][0]
    med_len = length_stats["med"][0]
    max_len = length_stats["max"][0]

    clean_text_wpm = _clean_text_expr(lowercase=False)
    wpm_mean = df.select(clean_text_wpm.str.extract_all(WORD_RE).list.len().alias("wc"))["wc"].mean()

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

    can_score = bool(
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

    # Secondary sort on user_id for deterministic ordering of ties.
    top = u.sort(["messageCount", "user_id"], descending=[True, False]).head(top_n)

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

    def safe_q(q: float) -> float | None:
        val = c.quantile(q)
        return round(float(val), 2) if val is not None else None

    return {
        "chatter_message_quantiles": {
            "p50": safe_q(0.50),
            "p75": safe_q(0.75),
            "p90": safe_q(0.90),
            "p95": safe_q(0.95),
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
        per_day = df.group_by(pl.col("ts").dt.date().alias("day")).len()
        all_days = pl.date_range(min_date, max_date, interval="1d", eager=True).alias("day")
        full_days = pl.DataFrame({"day": all_days}).join(per_day, on="day", how="left").fill_null(0)
        messages_per_day = [
            {"date": day.isoformat(), "count": int(count)}
            for day, count in zip(full_days["day"].to_list(), full_days["len"].to_list(), strict=True)
        ]

    top_peaks: list[dict] = []
    # group_by_dynamic handles a single row fine; no need for a >=2 gate.
    if df.height >= 1:
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
                df.select(pl.col("text").str.extract_all(EMOTE_TOKEN_RE).alias("w"))
                .explode("w", empty_as_null=True)
                .drop_nulls("w")
                .filter(pl.col("w").is_in(known_names))
                .group_by("w")
                .len()
            )
            for name, count in zip(catalog_counts["w"].to_list(), catalog_counts["len"].to_list(), strict=True):
                named_counts[name] = named_counts.get(name, 0) + int(count)

    seen_names = set(named_counts.keys())
    # Secondary key for deterministic tie ordering.
    top_emotes = sorted(named_counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
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
    edf = edf.filter((pl.col("emotes").list.len() >= 2) & (pl.col("emotes").list.len() <= MAX_EMOTES_PER_MSG))
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
    words = (
        df.select(_clean_text_expr().str.extract_all(WORD_RE).alias("w"))
        .explode("w", empty_as_null=True)
        .drop_nulls("w")
        .filter(~pl.col("w").is_in(list(stopwords)))
        .group_by("w")
        .len()
        .sort(["len", "w"], descending=[True, False])
        .head(limit)
    )
    return {"top_words": [{"word": w, "count": c} for w, c in zip(words["w"], words["len"], strict=True)]}


def _compute_commands(df: pl.DataFrame, top_n: int) -> dict:
    base = (
        df.filter(pl.col("text").str.starts_with("!"))
        .select(
            pl.col("text").str.strip_prefix("!").str.extract(COMMAND_RE, 0).str.to_lowercase().alias("cmd"),
            "user_id",
        )
        .drop_nulls("cmd")
    )

    messages_with_commands = base.height
    top_cmds = (
        base.group_by("cmd")
        .agg(pl.len().alias("count"), pl.col("user_id").n_unique().alias("unique_users"))
        .sort(["count", "cmd"], descending=[True, False])
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
    links_df = df.filter(pl.col("text").str.contains(URL_RE))
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

    # Extract URLs once; classify each URL individually so platform counts
    # and top_domains are consistent (link-level, not message-level).
    urls = (
        links_df.select(pl.col("text").str.extract_all(URL_RE).alias("url"))
        .explode("url", empty_as_null=True)
        .drop_nulls("url")
    )

    domains = (
        urls.select(
            pl.col("url").str.to_lowercase().str.extract(r"^(?:https?://)?(?:www\.)?([^/]+)", 1).alias("domain")
        )
        .drop_nulls("domain")
        .group_by("domain")
        .len()
        .sort(["len", "domain"], descending=[True, False])
        .head(top_n)
    )

    u_lower = urls["url"].str.to_lowercase()
    is_clip = u_lower.str.contains(r"clips\.twitch\.tv|twitch\.tv/\w+/clip/")
    is_yt = u_lower.str.contains(r"youtube\.com|youtu\.be")
    is_dc = u_lower.str.contains(r"discord\.(gg|com)")
    is_x = u_lower.str.contains(r"x\.com|twitter\.com")
    is_kick = u_lower.str.contains(r"kick\.com")
    any_platform = is_clip | is_yt | is_dc | is_x | is_kick

    return {
        "messages_with_links": messages_with_links,
        "top_domains": [{"domain": d, "count": c} for d, c in zip(domains["domain"], domains["len"], strict=True)],
        "platform_links": {
            "twitch_clips": int(is_clip.sum()),
            "youtube": int(is_yt.sum()),
            "discord": int(is_dc.sum()),
            "x_twitter": int(is_x.sum()),
            "kick": int(is_kick.sum()),
            "other": int((~any_platform).sum()),
        },
    }


def _compute_mentions(df: pl.DataFrame, top_n: int) -> dict:
    mentions_raw = (
        df.select(
            pl.col("username").str.to_lowercase().alias("from_user"),
            pl.col("text").str.extract_all(MENTION_RE).alias("mentions_raw"),
        )
        .explode("mentions_raw", empty_as_null=True)
        .drop_nulls("mentions_raw")
    )

    mentions_df = mentions_raw.with_columns(
        pl.col("mentions_raw").str.slice(1).str.to_lowercase().alias("mentions")
    ).drop_nulls("mentions")

    messages_with_mentions = df.filter(pl.col("text").str.contains(MENTION_RE)).height

    top_mens = (
        mentions_df.select(pl.col("mentions").alias("user"))
        .group_by("user")
        .len()
        .sort(["len", "user"], descending=[True, False])
        .head(top_n)
    )

    pairs = mentions_df.select(pl.col("from_user"), pl.col("mentions").alias("to_user")).filter(
        pl.col("from_user") != pl.col("to_user")
    )
    top_pairs = (
        pairs.group_by("from_user", "to_user")
        .len()
        .sort(["len", "from_user", "to_user"], descending=[True, False, False])
        .head(top_n)
    )

    return {
        "messages_with_mentions": messages_with_mentions,
        "top_mentions": [{"username": u, "count": c} for u, c in zip(top_mens["user"], top_mens["len"], strict=True)],
        "top_mention_pairs": [
            {"from_user": f, "to_user": t, "count": c}
            for f, t, c in zip(top_pairs["from_user"], top_pairs["to_user"], top_pairs["len"], strict=True)
        ],
    }


def _compute_health(df: pl.DataFrame, top_n: int) -> dict:
    # len_chars is functionally determined by text; grouping by both is redundant.
    dupes = (
        df.group_by("text")
        .agg(
            pl.len().alias("len"),
            pl.col("text").str.len_chars().first().alias("len_chars"),
        )
        .filter(pl.col("len") > 1)
    )
    dup_sum = dupes.select((pl.col("len") - 1).sum()).item() if not dupes.is_empty() else None
    duplicate_message_count = int(dup_sum) if dup_sum is not None else 0

    top_reps = dupes.sort(["len", "text"], descending=[True, False]).head(top_n)
    top_repeated_messages = []
    for text, count, length in zip(top_reps["text"], top_reps["len"], top_reps["len_chars"], strict=True):
        text_val = text if length <= MAX_REPEAT_TEXT_LEN else text[:MAX_REPEAT_TEXT_LEN] + "..."
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
    """Per-user activity sessions.

    A session starts when a user's consecutive messages are separated by
    more than ``gap_min`` minutes, or when the chatter changes. This is
    per-user, not channel-wide: on an active channel the channel-wide
    stream rarely has a 15-minute gap, which would collapse everything
    into one bucket.
    """
    if df.height <= 1:
        n = df.height
        return {
            "sessions": {
                "total_sessions": n,
                "avg_messages_per_session": float(n) if n else None,
                "avg_session_minutes": 0.0 if n else None,
                "longest_session_minutes": 0.0 if n else None,
            }
        }

    s = df.select("user_id", "ts").sort("user_id", "ts")
    s = s.with_columns(
        [
            pl.col("ts").diff().dt.total_seconds().alias("diff_sec"),
            (pl.col("user_id") != pl.col("user_id").shift(1)).fill_null(True).alias("user_changed"),
        ]
    )
    boundary = ((pl.col("diff_sec") >= gap_min * 60.0) | pl.col("user_changed")).fill_null(True)

    agg = (
        s.with_columns(boundary.cum_sum().alias("sid"))
        .group_by("user_id", "sid")
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


def _compute_message_classes(df: pl.DataFrame, twitch_emotes: pl.Series, emote_map: dict[str, str]) -> dict:
    txt = pl.col("text")
    r = txt.str.strip_chars_end()

    questions = int(df.filter(r.str.ends_with("?")).height)
    exclamations = int(df.filter(r.str.ends_with("!")).height)
    short_msgs = int(df.filter(txt.str.len_chars() <= 3).height)
    long_msgs = int(df.filter(txt.str.len_chars() >= 200).height)

    # Unicode-aware so Polish/Cyrillic/etc. aren't miscounted as non-letters.
    alpha_count = txt.str.extract_all(r"\p{L}").list.len()
    upper_count = txt.str.extract_all(r"\p{Lu}").list.len()
    all_caps = int(df.filter((alpha_count >= MIN_ALPHA_FOR_CAPS) & (upper_count >= (alpha_count * 0.8))).height)

    # Gather all known emote names (third-party catalog values + Twitch names)
    # so a message that is *only* emotes can be identified.
    known_emotes_lower: set[str] = {v.lower() for v in emote_map.values()}
    if not twitch_emotes.is_empty():
        twitch_names = twitch_emotes.explode(empty_as_null=True).drop_nulls().unique().to_list()
        known_emotes_lower.update(str(n).lower() for n in twitch_names)

    words = (
        txt.str.replace_all(URL_RE, " ")
        .str.replace_all(MENTION_RE, " ")
        .str.extract_all(EMOTE_TOKEN_RE)
        .list.eval(pl.element().str.to_lowercase())
    )

    if known_emotes_lower:
        # `is_in` accepts a Series/list; a set happens to work today but
        # isn't documented. Match the `list(stopwords)` style used elsewhere.
        known_emotes_list = list(known_emotes_lower)
        non_emote_words = (
            words.list.eval(pl.element().filter(~pl.element().is_in(known_emotes_list))).list.len()
        )
    else:
        non_emote_words = words.list.len()

    has_twitch_emote = twitch_emotes.list.len() > 0
    has_3rd_party_emote = words.list.len() > non_emote_words
    has_any_emote = has_twitch_emote | has_3rd_party_emote
    emote_only = int(df.filter(has_any_emote & (non_emote_words == 0)).height)

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
    tokens_df = (
        df.select(_clean_text_expr().str.extract_all(WORD_RE).alias("t")).filter(pl.col("t").list.len() >= 2)
    )

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
        .sort(["len", "phrase"], descending=[True, False])
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

    binned = (
        df.group_by_dynamic("ts", every="5m", period="5m", start_by="window", closed="left").agg(pl.len()).sort("ts")
    )
    if binned.height < 10:
        return []

    counts = binned["len"]
    mean = counts.mean()
    std = counts.std()
    if mean is None or std is None or std == 0:
        return []

    binned = binned.with_columns(((counts - mean) / std).alias("z_score"))
    # Cap output: with sigma=1.0 over a long range this can otherwise return
    # thousands of rows, bloating the jobs polling payload.
    anomalies = (
        binned.filter(pl.col("z_score").abs() >= sigma)
        .sort(pl.col("z_score").abs(), descending=True)
        .head(MAX_ANOMALIES)
    )

    return [
        {
            "window_start": r["ts"].isoformat(),
            "message_count": int(r["len"]),
            "z_score": round(float(r["z_score"]), 2),
        }
        for r in anomalies.iter_rows(named=True)
    ]


def _detect_language(df: pl.DataFrame) -> list[dict]:
    """Optional basic language breakdown. Requires the ``langdetect`` package."""
    try:
        from langdetect import DetectorFactory, detect  # type: ignore
        from langdetect.lang_detect_exception import LangDetectException  # type: ignore
    except ImportError:
        return []

    # Idempotent and cheap: no lock needed. Two jobs setting the same seed
    # concurrently is harmless.
    DetectorFactory.seed = 0

    cleaned = _clean_text_expr(lowercase=False)
    # Keep messages with a meaningful amount of alphabetic content (Unicode-
    # aware) so the detector isn't dominated by emote spam.
    candidates = (
        df.select(cleaned.alias("c"))
        .filter(pl.col("c").str.extract_all(r"\p{L}").list.len() >= MIN_ALPHA_CHARS_FOR_LANG)
        .get_column("c")
        .to_list()
    )
    if not candidates:
        return []

    rng = random.Random(42)
    sample_size = min(LANG_SAMPLE_SIZE, len(candidates))
    sample = rng.sample(candidates, sample_size)

    lang_counts: dict[str, int] = {}
    for text in sample:
        try:
            lang = detect(text)
        except LangDetectException:
            # Undetectable input (too short, emote-only, mixed scripts).
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
        # Let Pydantic defaults fill everything except required fields.
        return Result(
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
        stats.update(_compute_message_classes(df, twitch_emotes, emote_map))
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
#
# Monthly chunking: the requested range is split by calendar month and each
# month loads from its own cache chunk, so shifting the range by a day
# reuses the overlapping months instead of redownloading everything.
# Chunks track their fetched coverage; missing head/tail spans are
# downloaded and merged (deduped by message id), and a stale live month
# tops up only its tail — never the whole month.
#
# Note on coverage: a chunk stores a single [covered_from, covered_to]
# interval. When a new query lies outside the current interval, the head
# and tail spans are extended to *touch* the existing coverage, so the
# stored interval stays contiguous. This occasionally over-fetches (e.g.
# a 4-day request in a gap may fetch 19 days of empty space), but it keeps
# the single-interval model honest. A multi-interval model would avoid
# the over-fetch at the cost of a larger metadata change.


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


# Page-level retries handle seconds-long blips; this second line of defense
# handles the minute-long ones. Without it a single exhausted page discards
# every page already fetched for the month (save_month only runs on full
# success), and the next run recomputes the identical span.
SPAN_RETRY_COOLDOWN_S = 30.0
SPAN_RETRY_TICK_S = 5.0


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
    for span_from, span_to in spans:
        messages, span_truncated = await _fetch_span_resilient(
            api, params, span_from, span_to, on_page, label, progress, base
        )
        new_truncated = new_truncated or span_truncated
        if new_twitch_id is None:
            new_twitch_id = _extract_twitch_id(messages)
        new_frames.append(messages_to_frame(messages))

    if stored is not None:
        merged = pl.concat([stored[0], *new_frames], how="vertical")
    else:
        merged = pl.concat(new_frames, how="vertical") if len(new_frames) > 1 else new_frames[0]
    merged = _dedupe_by_id(merged).sort("ts")

    # Build new coverage as a list of intervals.
    new_cov = list(stored_cov)
    for span_from, span_to in spans:
        if not new_truncated:
            new_cov = log_cache.merge_coverage(new_cov, (span_from, span_to))

    if new_truncated:
        # Only the *new* frames can attest to how far we actually got.
        # `merged` also contains old cached rows and would falsely extend
        # coverage past a truncated span.
        new_merged = pl.concat(new_frames, how="vertical") if new_frames else merged
        _, data_hi = _span_extremes(new_merged)
        if data_hi is not None and spans:
            span_from = min(s for s, _ in spans)
            if span_from < data_hi:
                new_cov = log_cache.merge_coverage(new_cov, (span_from, data_hi))

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
    params: Params, progress: Callable[[float, str], None]
) -> tuple[pl.DataFrame, bool, bool, str | None, str | None]:
    """Fetch the range month by month over one shared HTTP client.

    Returns ``(frame, any_fetch, truncated, twitch_id, cached_at)``.
    ``cached_at`` is set only when every month came from cache.

    Two phases: first decide purely locally (chunk validity) whether any
    month needs downloading at all — a full hit stays fully offline. Only
    then, the requested range is clamped once to the channel's logged
    calendar, so pre-history/future edges never hit the network at all.
    """
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

    # Open the API client only if we actually need to fetch.
    async with HarambelogsAPI() if needs_fetch else nullcontext() as api:
        if needs_fetch:
            days = await channel_log_days(api, params.channel_id_type, params.channel)
            if days:
                first_day = min(days)
                last_day = max(days)
                first = datetime(first_day.year, first_day.month, first_day.day, tzinfo=UTC)
                last_end = datetime(last_day.year, last_day.month, last_day.day, tzinfo=UTC) + timedelta(days=1)
                clamped_from = max(req_from, first)
                clamped_to = min(req_to, last_end)
                if clamped_from != req_from or clamped_to != req_to:
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
    df = _dedupe_by_id(df).sort("ts")

    cached_at = (
        _as_utc(datetime.fromtimestamp(newest_cached_at, UTC)).isoformat()
        if (not any_fetch and newest_cached_at is not None)
        else None
    )
    return df, any_fetch, overall_truncated, twitch_id, cached_at


async def _run_all(
    params: Params, progress: Callable[[float, str], None]
) -> tuple[pl.DataFrame, bool, bool, str | None, str | None, dict[str, str]]:
    df, any_fetch, truncated, twitch_id, cached_at = await _run_chunked(params, progress)
    progress(80.0, "fetching emotes")
    emote_map = await _safe_fetch_emotes(params.channel, twitch_id)
    return df, any_fetch, truncated, twitch_id, cached_at, emote_map


def run(params: Params, progress: Callable[[float, str], None] = lambda pct, msg="": None) -> Result:
    # from_date < to_date is enforced by Params._validate_date_order.
    df, any_fetch, truncated, twitch_id, cached_at, emote_map = asyncio.run(_run_all(params, progress))

    progress(85.0, "building dataframe & computing stats")
    stats = compute_stats(df, params, emote_map)
    stats["truncated"] = truncated
    stats["from_cache"] = not any_fetch
    stats["cached_at"] = cached_at
    progress(100.0, "done" if any_fetch else "done (cached)")
    return Result(**stats)
