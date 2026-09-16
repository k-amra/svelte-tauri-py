"""Overview and per-user aggregates."""
from __future__ import annotations

import polars as pl

from ..constants import WORD_RE
from ..frame import clean_text_expr


def compute_overview(df: pl.DataFrame) -> dict:
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

    clean_text_wpm = clean_text_expr(lowercase=False)
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


def compute_users(df: pl.DataFrame, top_n: int, include_engagement: bool) -> dict:
    has_channel = "channel" in df.columns

    aggs = [
        pl.len().alias("messageCount"),
        pl.col("username").last().alias("username"),
        pl.col("ts").min().alias("firstSeen"),
        pl.col("ts").max().alias("lastSeen"),
        pl.col("ts").dt.date().n_unique().alias("activeDays"),
        pl.col("text").str.len_chars().mean().alias("avg_msg_len"),
    ]
    if has_channel:
        aggs.append(pl.col("channel").unique().alias("channels"))

    u = df.group_by("user_id").agg(*aggs)

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
        entry: dict = {
            "user_id": r["user_id"],
            "username": r["username"],
            "messageCount": int(r["messageCount"]),
            "activeDays": int(r["activeDays"]),
            "firstSeen": r["firstSeen"].isoformat() if r["firstSeen"] else None,
            "lastSeen": r["lastSeen"].isoformat() if r["lastSeen"] else None,
            "engagement_score": round(float(score), 4) if score is not None else None,
        }
        if has_channel:
            # Polars returns `None` for empty groups; normalize to a list.
            entry["channels"] = sorted(r.get("channels") or [])
        top_chatters.append(entry)
    return {"top_chatters": top_chatters}


def compute_chatter_dist(df: pl.DataFrame) -> dict:
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
            "p99": safe_q(0.99),
        }
    }


def compute_activity_per_day(df: pl.DataFrame) -> dict:
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
