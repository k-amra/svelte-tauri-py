"""Dataframe construction and small parsers shared by every analytics module."""
from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from app.services.harambelogs_models import FullMessage

from .constants import MENTION_RE, URL_RE


def clean_text_expr(*, lowercase: bool = True) -> pl.Expr:
    """URL/mention-stripped text expression, shared by word/phrase/language passes.

    Args:
        lowercase: apply `.str.to_lowercase()`. `detect_language` wants
            original case preserved so the detector sees real casing.
    """
    expr = pl.col("text").str.replace_all(URL_RE, " ").str.replace_all(MENTION_RE, " ")
    return expr.str.to_lowercase() if lowercase else expr


def parse_ts(value: datetime | str) -> datetime | None:
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


def get_tag(tags: dict | None, key: str) -> str | None:
    if not tags:
        return None
    val = tags.get(key)
    return str(val) if val is not None else None


def get_role(badges: str | None) -> str:
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
        ts = parse_ts(m.timestamp)
        if ts is None:
            continue
        user_ids.append(get_tag(m.tags, "user-id") or m.username)
        usernames.append(m.username)
        texts.append(m.text)
        stamps.append(ts)
        emotes.append(get_tag(m.tags, "emotes"))
        ids.append(m.id)
        roles.append(get_role(get_tag(m.tags, "badges")))

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


def dedupe_by_id(df: pl.DataFrame) -> pl.DataFrame:
    """Dedupe by message id, keeping the last occurrence.
    Order-preserving: null-id rows stay in their original position.

    Null-id rows are kept as distinct rows (not collapsed), so a message
    whose upstream id is missing cannot silently delete other null-id
    messages. In practice this only matters at month boundaries and in
    historical data.
    """
    if df.is_empty() or "id" not in df.columns:
        return df
    indexed = df.with_row_index("__dedupe_idx")
    non_null = indexed.filter(pl.col("id").is_not_null())
    null_part = indexed.filter(pl.col("id").is_null())
    if not non_null.is_empty():
        non_null = non_null.unique(subset=["id"], keep="last", maintain_order=True)
    if null_part.is_empty():
        return non_null.drop("__dedupe_idx")
    out = pl.concat([non_null, null_part], how="vertical")
    return out.sort("__dedupe_idx").drop("__dedupe_idx")


def extract_twitch_id(messages: list[FullMessage]) -> str | None:
    for m in messages:
        room_id = get_tag(m.tags, "room-id")
        if room_id:
            return room_id
    return None


def parse_twitch_emotes(df: pl.DataFrame) -> pl.Series:
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
