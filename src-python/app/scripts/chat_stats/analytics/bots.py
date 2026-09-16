"""Heuristic bot-likelihood scoring for the most active chatters."""
from __future__ import annotations

import polars as pl

from ..constants import BOT_MIN_MESSAGES, BOT_TOP_N


def compute_bot_scores(df: pl.DataFrame, top_n: int = BOT_TOP_N) -> dict:
    """Heuristic bot-likelihood for the most active chatters.

    Signals (each contributes to a bounded score):
      - regular_interval: low stdev of inter-message gaps (< 5s stddev)
      - low_diversity:    unique-text ratio < 0.3
      - command_spam:     >50% of messages start with '!'

    Not a classifier — a triage list. Score is a weighted sum in [0, 1].
    """
    if df.height == 0:
        return {"bot_likelihood": []}

    per_user = (
        df.sort("user_id", "ts")
        .with_columns(pl.col("ts").diff().dt.total_seconds().over("user_id").alias("gap_s"))
        .group_by("user_id")
        .agg(
            pl.col("username").last().alias("username"),
            pl.len().alias("n"),
            pl.col("gap_s").std().alias("gap_std"),
            pl.col("text").n_unique().alias("unique_texts"),
            pl.col("text").str.starts_with("!").mean().alias("command_ratio"),
        )
        .filter(pl.col("n") >= BOT_MIN_MESSAGES)
        .with_columns((pl.col("unique_texts") / pl.col("n")).alias("diversity_ratio"))
    )

    if per_user.is_empty():
        return {"bot_likelihood": []}

    def signals_for(row: dict) -> list[str]:
        s: list[str] = []
        if row["gap_std"] is not None and row["gap_std"] < 5.0:
            s.append("regular_interval")
        if row["diversity_ratio"] < 0.3:
            s.append("low_diversity")
        if row["command_ratio"] > 0.5:
            s.append("command_spam")
        return s

    weights = {"regular_interval": 0.4, "low_diversity": 0.4, "command_spam": 0.2}

    scored: list[dict] = []
    for r in per_user.iter_rows(named=True):
        sigs = signals_for(r)
        score = min(1.0, sum(weights[s] for s in sigs))
        if score > 0:
            scored.append(
                {
                    "user_id": r["user_id"],
                    "username": r["username"],
                    "score": round(score, 3),
                    "signals": sigs,
                }
            )
    scored.sort(key=lambda x: (-x["score"], x["user_id"]))
    return {"bot_likelihood": scored[:top_n]}
