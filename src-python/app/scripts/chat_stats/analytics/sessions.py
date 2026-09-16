"""Per-user activity sessions."""
from __future__ import annotations

import polars as pl


def compute_sessions(df: pl.DataFrame, gap_min: int) -> dict:
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

    # Session-length distribution over the existing durations.
    dur = agg["dur_min"]
    median_dur = dur.median()
    p90_dur = dur.quantile(0.90)

    return {
        "sessions": {
            "total_sessions": agg.height,
            "avg_messages_per_session": float(agg["n"].mean()) if agg.height else None,
            "avg_session_minutes": float(dur.mean()) if agg.height else None,
            "longest_session_minutes": float(dur.max()) if agg.height else None,
            "median_session_minutes": round(float(median_dur), 2) if median_dur is not None else None,
            "p90_session_minutes": round(float(p90_dur), 2) if p90_dur is not None else None,
        }
    }
