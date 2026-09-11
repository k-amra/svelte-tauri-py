"""Twitch / BTTV / FFZ / 7TV emote analytics."""
from __future__ import annotations

import math

import polars as pl

from ..constants import EMOTE_TOKEN_RE, MAX_EMOTES_PER_MSG


def count_emotes(
    df: pl.DataFrame,
    twitch_emotes: pl.Series,
    emote_map: dict[str, str],
    limit: int,
) -> tuple[list[dict], set[str]]:
    """Return (top emotes, set of all seen emote names).

    ``twitch_emotes`` is produced once by :func:`parse_twitch_emotes` so this
    function does not re-walk the ``emotes_tag`` string.
    """
    named_counts: dict[str, int] = {}

    # Twitch emotes (from tags, already parsed).
    emote_df = pl.DataFrame({"e": twitch_emotes}).explode("e", empty_as_null=True).drop_nulls("e")
    if not emote_df.is_empty():
        counts = emote_df.group_by("e").len()
        for name, count in zip(counts["e"].to_list(), counts["len"].to_list(), strict=True):
            named_counts[str(name)] = int(count)

    # Third-party (BTTV/FFZ/7TV) tokens matched by name against the catalog.
    # Names already seen as Twitch emotes in this range are excluded to avoid
    # double counting across the two passes.
    if emote_map and "text" in df.columns:
        known_names = sorted(set(emote_map.values()) - set(named_counts))
        if known_names:
            catalog_counts = (
                df.select(pl.col("text").str.extract_all(EMOTE_TOKEN_RE).alias("w"))
                .explode("w", empty_as_null=True)
                .drop_nulls("w")
                .filter(pl.col("w").is_in(known_names))
                .group_by("w")
                .len()
            )
            for name, count in zip(catalog_counts["w"].to_list(), catalog_counts["len"].to_list(), strict=True):
                named_counts[name] = named_counts.get(name, 0) + int(count)

    seen_names = set(named_counts.keys())
    # Secondary key for deterministic tie ordering.
    top_emotes = sorted(named_counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [{"name": n, "count": c} for n, c in top_emotes], seen_names


def emote_pairs_frame(twitch_emotes: pl.Series) -> pl.DataFrame:
    """All unique within-message emote pairs (message-bounded, deduped)."""
    if len(twitch_emotes) == 0:
        return pl.DataFrame({"emotes": [], "emotes_2": []})
    edf = pl.DataFrame({"msg_id": list(range(len(twitch_emotes))), "emotes": twitch_emotes})
    edf = edf.filter(pl.col("emotes").list.len() >= 2).with_columns(
        pl.col("emotes").list.unique().alias("emotes")
    )
    edf = edf.filter(
        (pl.col("emotes").list.len() >= 2) & (pl.col("emotes").list.len() <= MAX_EMOTES_PER_MSG)
    )
    if edf.is_empty():
        return pl.DataFrame({"emotes": [], "emotes_2": []})
    exploded = edf.explode("emotes", empty_as_null=True)
    return (
        exploded.join(exploded, on="msg_id", suffix="_2")
        .filter(pl.col("emotes") < pl.col("emotes_2"))
        .select("emotes", "emotes_2")
    )


def compute_emote_pairs(pairs: pl.DataFrame, limit: int) -> list[dict]:
    """All unique unordered emote pairs co-occurring within a single message.

    Takes the pre-built pairs frame (see :func:`emote_pairs_frame`): one Polars
    pass in the caller, no Python per-message loops here.
    """
    if pairs.is_empty():
        return []
    top = pairs.group_by("emotes", "emotes_2").len().sort("len", descending=True).head(limit)
    return [
        {"emote1": a, "emote2": b, "count": int(c)}
        for a, b, c in zip(top["emotes"], top["emotes_2"], top["len"], strict=True)
    ]


def compute_emote_centrality(pairs: pl.DataFrame, top_n: int) -> dict:
    """Degree centrality over the shared emote-pairs frame.

    Frequency tells you what's popular; centrality tells you what connects
    different emote clusters. Uses the pre-truncation frame so rare
    co-occurrences still count.
    """
    if pairs.is_empty():
        return {"emote_centrality": []}

    both = pl.concat(
        [
            pairs.select(pl.col("emotes").alias("e"), pl.col("emotes_2").alias("other")),
            pairs.select(pl.col("emotes_2").alias("e"), pl.col("emotes").alias("other")),
        ]
    )
    centrality = (
        both.group_by("e")
        .agg(pl.col("other").n_unique().alias("distinct_co_occurrences"))
        .sort(["distinct_co_occurrences", "e"], descending=[True, False])
        .head(top_n)
    )

    return {
        "emote_centrality": [
            {"emote": r["e"], "distinct_co_occurrences": int(r["distinct_co_occurrences"])}
            for r in centrality.iter_rows(named=True)
        ]
    }


def compute_emote_entropy(twitch_emotes: pl.Series) -> dict:
    """Shannon entropy (bits) over the Twitch emote frequency distribution.

    0.0 means a single emote dominates; None means there are no emote uses
    at all to measure.
    """
    if len(twitch_emotes) == 0:
        return {"emote_entropy": None}
    exploded = pl.DataFrame({"e": twitch_emotes}).explode("e", empty_as_null=True).drop_nulls("e")
    if exploded.is_empty():
        return {"emote_entropy": None}
    counts = exploded.group_by("e").len()["len"].to_list()
    total = sum(counts)
    if total == 0:
        return {"emote_entropy": None}
    if len(counts) < 2:
        return {"emote_entropy": 0.0}
    h = -sum((c / total) * math.log2(c / total) for c in counts if c > 0)
    return {"emote_entropy": round(h, 4)}


def compute_emote_diversity(df: pl.DataFrame, twitch_emotes: pl.Series, top_n: int) -> dict:
    """Per-user emote vocabulary breadth (Twitch-native emotes, like pairs)."""
    if df.is_empty() or len(twitch_emotes) != df.height:
        return {"emote_diversity": []}

    edf = pl.DataFrame(
        {"user_id": df["user_id"], "username": df["username"], "emotes": twitch_emotes}
    ).filter(pl.col("emotes").list.len() > 0)
    if edf.is_empty():
        return {"emote_diversity": []}

    grouped = (
        edf.explode("emotes", empty_as_null=True)
        .group_by("user_id")
        .agg(
            pl.col("username").last().alias("username"),
            pl.len().alias("total_emote_uses"),
            pl.col("emotes").n_unique().alias("unique_emotes"),
        )
        .filter(pl.col("total_emote_uses") >= 5)  # minimum signal threshold
        .with_columns(
            (pl.col("unique_emotes") / pl.col("total_emote_uses")).round(4).alias("diversity_ratio")
        )
        .sort(["total_emote_uses", "user_id"], descending=[True, False])
        .head(top_n)
    )

    return {
        "emote_diversity": [
            {
                "user_id": r["user_id"],
                "username": r["username"],
                "total_emote_uses": int(r["total_emote_uses"]),
                "unique_emotes": int(r["unique_emotes"]),
                "diversity_ratio": float(r["diversity_ratio"]),
            }
            for r in grouped.iter_rows(named=True)
        ]
    }
