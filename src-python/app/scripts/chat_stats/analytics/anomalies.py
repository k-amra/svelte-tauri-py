"""5-minute-window anomaly detection with a Poisson tail."""
from __future__ import annotations

import math

import polars as pl

from ..constants import MAX_ANOMALIES, POISSON_NORMAL_APPROX_LAMBDA


def poisson_upper_tail(k: int, lam: float) -> float:
    """P(X >= k) for X ~ Poisson(lam)."""
    if k <= 0:
        return 1.0
    if lam < POISSON_NORMAL_APPROX_LAMBDA:
        # Direct: sum terms upward. Use log-gamma to avoid factorial overflow.
        log_lam = math.log(lam) if lam > 0 else float("-inf")
        if log_lam == float("-inf"):
            return 0.0
        log_p = -lam + k * log_lam - math.lgamma(k + 1)
        total = math.exp(log_p)
        j = k
        while True:
            j += 1
            log_p += log_lam - math.log(j)
            term = math.exp(log_p)
            if term < 1e-15:
                break
            total += term
        return min(1.0, total)
    # Normal approximation with continuity correction.
    z = (k - 0.5 - lam) / math.sqrt(lam)
    return 0.5 * math.erfc(z / math.sqrt(2))


def poisson_lower_tail(k: int, lam: float) -> float:
    """P(X <= k) for X ~ Poisson(lam)."""
    if k < 0:
        return 0.0
    if lam < POISSON_NORMAL_APPROX_LAMBDA:
        log_lam = math.log(lam) if lam > 0 else float("-inf")
        if log_lam == float("-inf"):
            return 1.0 if k >= 0 else 0.0
        log_p = -lam
        total = math.exp(log_p)
        for j in range(1, k + 1):
            log_p += log_lam - math.log(j)
            total += math.exp(log_p)
        return min(1.0, total)
    z = (k + 0.5 - lam) / math.sqrt(lam)
    return 0.5 * math.erfc(-z / math.sqrt(2))


def detect_anomalies(df: pl.DataFrame, sigma: float) -> list[dict]:
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

    lam = float(mean)
    out: list[dict] = []
    for r in anomalies.iter_rows(named=True):
        k = int(r["len"])
        z = float(r["z_score"])
        # Upper tail for spikes, lower tail for dips. Both are "how extreme
        # under a Poisson(mean) null for this channel".
        p = poisson_upper_tail(k, lam) if z > 0 else poisson_lower_tail(k, lam)
        out.append(
            {
                "window_start": r["ts"].isoformat(),
                "message_count": k,
                "z_score": round(z, 2),
                "p_value": round(p, 6),
            }
        )
    return out
