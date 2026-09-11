"""Mention graph, mutual mentions, and quote-reply inference."""
from __future__ import annotations

import polars as pl

from ..constants import MENTION_RE, REPLY_TOP_N, REPLY_WINDOW_S


def mention_pairs_frame(df: pl.DataFrame) -> pl.DataFrame:
    """Exploded (from_user, to_user) mention edges, self-mentions dropped.

    Shared by :func:`compute_mentions`, :func:`compute_mention_graph` and
    :func:`compute_mutual_mentions` so the text column is only exploded once.
    """
    mentions_raw = (
        df.select(
            pl.col("username").str.to_lowercase().alias("from_user"),
            pl.col("text").str.extract_all(MENTION_RE).alias("mentions_raw"),
        )
        .explode("mentions_raw", empty_as_null=True)
        .drop_nulls("mentions_raw")
    )
    return (
        mentions_raw.with_columns(
            pl.col("mentions_raw").str.slice(1).str.to_lowercase().alias("to_user")
        )
        .drop_nulls("to_user")
        .filter(pl.col("from_user") != pl.col("to_user"))
        .select("from_user", "to_user")
    )


def compute_mentions(df: pl.DataFrame, top_n: int, pairs: pl.DataFrame) -> dict:
    messages_with_mentions = df.filter(pl.col("text").str.contains(MENTION_RE)).height
    if pairs.is_empty():
        return {"messages_with_mentions": messages_with_mentions, "top_mentions": [], "top_mention_pairs": []}

    top_mens = (
        pairs.group_by(pl.col("to_user").alias("user"))
        .len()
        .sort(["len", "user"], descending=[True, False])
        .head(top_n)
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


def compute_mention_graph(pairs: pl.DataFrame, top_n: int) -> dict:
    """Directed in/out degree plus total, over the shared mention edges."""
    if pairs.is_empty():
        return {"mention_graph": []}

    out_deg = pairs.group_by(pl.col("from_user").alias("username")).len().rename({"len": "mentions_out"})
    in_deg = pairs.group_by(pl.col("to_user").alias("username")).len().rename({"len": "mentions_in"})

    graph = (
        out_deg.join(in_deg, on="username", how="full", coalesce=True)
        .with_columns(
            [
                pl.col("mentions_in").fill_null(0),
                pl.col("mentions_out").fill_null(0),
            ]
        )
        .with_columns((pl.col("mentions_in") + pl.col("mentions_out")).alias("degree"))
        .sort(["degree", "username"], descending=[True, False])
        .head(top_n)
    )

    return {
        "mention_graph": [
            {
                "username": r["username"],
                "mentions_in": int(r["mentions_in"]),
                "mentions_out": int(r["mentions_out"]),
                "degree": int(r["degree"]),
            }
            for r in graph.iter_rows(named=True)
        ]
    }


def compute_quote_replies(df: pl.DataFrame, top_n: int = REPLY_TOP_N) -> dict:
    """Directed A→B reply counts inferred from mentions + recency.

    A "reply" is: message by A at time t contains @B, and B posted within
    REPLY_WINDOW_S before t. Not ground truth (no reply API exists), but the
    right shape for finding back-and-forth conversations. Signal is
    correlational, not causal.
    """
    if df.height < 2:
        return {"quote_reply_count": 0, "quote_reply_pairs": []}

    # Flatten message-mention edges.
    mentions = (
        df.select(
            pl.col("ts").alias("ts_reply"),
            pl.col("username").str.to_lowercase().alias("from_user"),
            pl.col("text").str.extract_all(MENTION_RE).alias("mentions_raw"),
        )
        .explode("mentions_raw", empty_as_null=True)
        .drop_nulls("mentions_raw")
        .with_columns(pl.col("mentions_raw").str.slice(1).str.to_lowercase().alias("to_user"))
        .drop("mentions_raw")
        .filter(pl.col("from_user") != pl.col("to_user"))
        .sort("ts_reply")
    )
    if mentions.is_empty():
        return {"quote_reply_count": 0, "quote_reply_pairs": []}

    # Candidate reply targets: every message by every user.
    targets = df.select(
        pl.col("ts").alias("ts_target"),
        pl.col("username").str.to_lowercase().alias("target_user"),
    ).sort("ts_target")

    # asof join: for each mention, find the most recent prior message by the
    # mentioned user. Both frames are sorted on their join timestamp (polars
    # can't verify that with by-groups, hence check_sortedness=False).
    matched = mentions.join_asof(
        targets,
        left_on="ts_reply",
        right_on="ts_target",
        by_left="to_user",
        by_right="target_user",
        strategy="backward",
        check_sortedness=False,
    )

    # Filter to within the reply window; drop nulls (no prior message).
    matched = matched.filter(
        pl.col("ts_target").is_not_null()
        & ((pl.col("ts_reply") - pl.col("ts_target")).dt.total_seconds() <= REPLY_WINDOW_S)
    )
    reply_count = matched.height

    top = (
        matched.group_by("from_user", "to_user")
        .len()
        .sort(["len", "from_user", "to_user"], descending=[True, False, False])
        .head(top_n)
    )

    return {
        "quote_reply_count": reply_count,
        "quote_reply_pairs": [
            {"from_user": r["from_user"], "to_user": r["to_user"], "count": int(r["len"])}
            for r in top.iter_rows(named=True)
        ],
    }


def compute_mutual_mentions(pairs: pl.DataFrame, top_n: int) -> dict:
    """Unordered user pairs that mention each other (both directions)."""
    if pairs.is_empty():
        return {"mutual_mention_pairs": []}

    edges = pairs.group_by("from_user", "to_user").len().rename({"len": "count"})

    ab = edges.rename({"from_user": "user_a", "to_user": "user_b"})
    ba = edges.rename({"from_user": "user_b", "to_user": "user_a", "count": "count_ba"})

    mutual = (
        ab.join(ba, on=["user_a", "user_b"], how="inner")
        .with_columns((pl.col("count") + pl.col("count_ba")).alias("total"))
        .filter(pl.col("user_a") < pl.col("user_b"))  # keep one direction only
        .sort(["total", "user_a", "user_b"], descending=[True, False, False])
        .head(top_n)
    )

    return {
        "mutual_mention_pairs": [
            {
                "user_a": r["user_a"],
                "user_b": r["user_b"],
                "count_ab": int(r["count"]),
                "count_ba": int(r["count_ba"]),
                "total": int(r["total"]),
            }
            for r in mutual.iter_rows(named=True)
        ]
    }
