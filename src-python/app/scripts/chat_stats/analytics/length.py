"""Per-day average message-length trend (OLS slope, chars/day)."""
from __future__ import annotations

import polars as pl


def compute_length_trend(df: pl.DataFrame) -> dict:
    """Per-day average message length + OLS slope (chars/day, closed form)."""
    if df.height < 2:
        return {"message_length_trend_slope": None}

    per_day = (
        df.group_by(pl.col("ts").dt.date().alias("day"))
        .agg(pl.col("text").str.len_chars().mean().alias("avg_len"))
        .sort("day")
    )
    if per_day.height < 2:
        return {"message_length_trend_slope": None}

    xs = list(range(per_day.height))
    ys = per_day["avg_len"].to_list()
    n = len(xs)
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys, strict=True))
    sxx = sum(x * x for x in xs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return {"message_length_trend_slope": None}
    slope = (n * sxy - sx * sy) / denom
    return {"message_length_trend_slope": round(slope, 4)}
