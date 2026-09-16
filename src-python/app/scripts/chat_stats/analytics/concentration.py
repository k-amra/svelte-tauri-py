"""Concentration metrics: Gini, top-share, Lorenz curve."""
from __future__ import annotations

import math

import polars as pl

from ..constants import LORENZ_FRACTIONS


def compute_concentration(df: pl.DataFrame) -> dict:
    counts_list = df.group_by("user_id").len().sort("len", descending=True)["len"].to_list()
    if not counts_list:
        return {"concentration": {}}

    total = sum(counts_list)
    n = len(counts_list)
    # Gini via the ordered-statistics form:
    #   G = |sum((2i - n - 1) * x_i)| / (n * sum(x))
    # over ascending x. Cheap on the small `counts_list` and avoids the
    # cumulative-sum loop the textbook formula would need.
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


def compute_lorenz(df: pl.DataFrame) -> dict:
    """Fixed points on the Lorenz curve: where concentration actually lives."""
    counts_list = df.group_by("user_id").len().sort("len", descending=True)["len"].to_list()
    if not counts_list:
        return {"lorenz_samples": []}

    total = sum(counts_list)
    n = len(counts_list)
    if total == 0:
        return {"lorenz_samples": []}

    cumulative = 0
    idx = 0
    samples: list[dict] = []
    for frac in LORENZ_FRACTIONS:
        cutoff = max(1, math.ceil(n * frac))
        while idx < cutoff:
            cumulative += counts_list[idx]
            idx += 1
        samples.append(
            {
                "top_pct": round(frac * 100, 2),
                "message_share_pct": round(cumulative / total * 100, 2),
            }
        )
    return {"lorenz_samples": samples}
