"""Monday-anchored weekly cohort retention."""
from __future__ import annotations

import polars as pl

from ..constants import COHORT_MAX_WEEKS


def compute_cohort_retention(df: pl.DataFrame) -> dict:
    """Monday-anchored signup cohorts × trailing retention (bounded 8×9)."""
    if df.height == 0:
        return {"cohort_retention": []}

    # Monday-aligned active weeks per user.
    active = df.select("user_id", pl.col("ts").dt.truncate("1w").alias("week")).unique()
    first_week = active.group_by("user_id").agg(pl.col("week").min().alias("cohort_week"))
    joined = active.join(first_week, on="user_id", how="left").with_columns(
        ((pl.col("week") - pl.col("cohort_week")).dt.total_days() / 7).cast(pl.Int32).alias("week_offset")
    )

    # Group sizes: number of users who first appeared in each cohort week.
    sizes = first_week.group_by("cohort_week").agg(pl.len().alias("cohort_size"))

    # Active count per (cohort, offset).
    cells = joined.group_by("cohort_week", "week_offset").agg(
        pl.col("user_id").n_unique().alias("active")
    )
    cells = cells.join(sizes, on="cohort_week", how="left").with_columns(
        (pl.col("active") / pl.col("cohort_size") * 100).round(2).alias("retention_pct")
    )

    # Cap: most recent COHORT_MAX_WEEKS cohorts, offsets 0..COHORT_MAX_WEEKS.
    # Two plain list columns (not pl.struct in agg): struct-in-agg yields
    # List(Struct) on some Polars versions and raises on others.
    cohorts = (
        cells.filter(pl.col("week_offset") <= COHORT_MAX_WEEKS)
        .filter(pl.col("week_offset") >= 0)
        .sort(["cohort_week", "week_offset"])
        .group_by("cohort_week", maintain_order=True)
        .agg(
            pl.col("cohort_size").first(),
            pl.col("week_offset").alias("offsets"),
            pl.col("retention_pct").alias("retentions"),
        )
        .sort("cohort_week", descending=True)
        .head(COHORT_MAX_WEEKS)
        .sort("cohort_week")
    )

    rows = []
    for r in cohorts.iter_rows(named=True):
        offsets = r["offsets"]
        retentions = r["retentions"]
        rows.append(
            {
                "cohort_week": r["cohort_week"].date().isoformat(),
                "cohort_size": int(r["cohort_size"]),
                "retention": [
                    {"week_offset": int(o), "retention_pct": float(p)}
                    for o, p in zip(offsets, retentions, strict=True)
                ],
            }
        )
    return {"cohort_retention": rows}
