"""Time-bucketed analytics: hourly, weekday, daily, seasonality, first-seen."""
from __future__ import annotations

from datetime import datetime

import polars as pl


def decompose_weekly_seasonality(
    messages_per_day: list[dict],
) -> tuple[list[dict], list[float] | None]:
    """Split messages_per_day into (trend, weekday_index).

    Trend is a 7-day centered moving average. weekday_index is the ratio
    actual/trend averaged per weekday (Mon..Sun), normalized so its mean
    is 1.0. Returns ([], None) for ranges shorter than 7 days.
    """
    if len(messages_per_day) < 7:
        return [], None

    counts = [int(d["count"]) for d in messages_per_day]
    n = len(counts)
    half = 3

    trend: list[dict] = []
    for i, d in enumerate(messages_per_day):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        window = counts[lo:hi]
        trend.append({"date": d["date"], "count": round(sum(window) / len(window), 2)})

    per_weekday: dict[int, list[float]] = {i: [] for i in range(7)}
    for i, d in enumerate(messages_per_day):
        t = trend[i]["count"]
        if t <= 0:
            continue
        # Python weekday(): Mon=0..Sun=6, matching WEEKDAY_LABELS on the frontend.
        wd = datetime.fromisoformat(d["date"]).weekday()
        per_weekday[wd].append(counts[i] / t)

    means = [sum(vs) / len(vs) if vs else 1.0 for vs in per_weekday.values()]
    overall = sum(means) / 7 if any(means) else 1.0
    if overall == 0:
        return trend, None
    seasonality = [round(m / overall, 4) for m in means]
    return trend, seasonality


def compute_time(df: pl.DataFrame) -> dict:
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
    peak_concurrent: int | None = None
    peak_concurrent_window: str | None = None
    # group_by_dynamic handles a single row fine; no need for a >=2 gate.
    if df.height >= 1:
        binned = (
            df.group_by_dynamic("ts", every="5m", period="5m", start_by="window", closed="left").agg(
                pl.len().alias("n"),
                pl.col("user_id").n_unique().alias("unique_chatters"),
            )
        )
        # Peak messages (existing) — top 3.
        p = binned.sort("n", descending=True).head(3)
        for r in p.iter_rows(named=True):
            top_peaks.append(
                {
                    "window_start": r["ts"].isoformat(),
                    "message_count": int(r["n"]),
                }
            )
        # Peak concurrency (new) — single row out of the same bins.
        top_conc = binned.sort("unique_chatters", descending=True).head(1)
        if not top_conc.is_empty():
            r = top_conc.row(0, named=True)
            peak_concurrent = int(r["unique_chatters"])
            peak_concurrent_window = r["ts"].isoformat()

    trend_by_day, weekly_seasonality = decompose_weekly_seasonality(messages_per_day)

    return {
        "activity_by_hour": hourly,
        "activity_by_weekday_hour": heatmap,
        "messages_per_day": messages_per_day,
        "top_peaks_5m": top_peaks,
        "peak_concurrent_chatters": peak_concurrent,
        "peak_concurrent_window": peak_concurrent_window,
        "trend_by_day": trend_by_day,
        "weekly_seasonality": weekly_seasonality,
    }


def compute_first_message_hours(df: pl.DataFrame) -> dict:
    """Hour-of-day histogram of each user's first message *in the range*."""
    if df.height == 0:
        return {"first_message_hours": [0] * 24}

    first_per_user = df.group_by("user_id").agg(pl.col("ts").min().alias("first_ts"))
    histogram = [0] * 24
    for h, count in (
        first_per_user.select(pl.col("first_ts").dt.hour().alias("h")).group_by("h").len().iter_rows()
    ):
        histogram[int(h)] = int(count)
    return {"first_message_hours": histogram}


def compute_new_returning(df: pl.DataFrame) -> dict:
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
