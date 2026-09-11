"""Word-level analytics: top words, phrases, commands, hapax, Zipf."""
from __future__ import annotations

import math

import polars as pl

from ..constants import COMMAND_RE, WORD_RE, WORDS_ZIPF_MAX_RANK
from ..frame import clean_text_expr


def compute_words(df: pl.DataFrame, stopwords: frozenset[str], limit: int) -> dict:
    """Top words, type-token ratio, hapax ratio, and Zipf slope.

    NOTE: TTR (vocab_richness) and hapax_ratio are length-dependent —
    longer ranges read lower. Compare only across similar spans.
    """
    words = (
        df.select(clean_text_expr().str.extract_all(WORD_RE).alias("w"))
        .explode("w", empty_as_null=True)
        .drop_nulls("w")
        .filter(~pl.col("w").is_in(list(stopwords)))
    )

    if words.is_empty():
        return {
            "top_words": [],
            "vocab_richness": None,
            "unique_word_count": 0,
            "hapax_ratio": None,
            "zipf_slope": None,
        }

    counts = words.group_by("w").len().sort(["len", "w"], descending=[True, False])

    total = int(counts["len"].sum())
    unique = counts.height
    hapax = int((counts["len"] == 1).sum())

    # Zipf: fit log(freq) ~ slope * log(rank) over the head.
    # Slope ~-1.0 is textbook Zipfian; real chat usually lands -0.7..-1.1.
    head = counts.head(WORDS_ZIPF_MAX_RANK)
    if head.height >= 10:
        freqs = head["len"].to_list()
        xs = [math.log(i + 1) for i in range(len(freqs))]  # 1-indexed rank
        ys = [math.log(f) for f in freqs]
        n = len(xs)
        sx, sy = sum(xs), sum(ys)
        sxy = sum(x * y for x, y in zip(xs, ys, strict=True))
        sxx = sum(x * x for x in xs)
        denom = n * sxx - sx * sx
        zipf_slope: float | None = round((n * sxy - sx * sy) / denom, 4) if denom else None
    else:
        zipf_slope = None

    top = counts.head(limit)

    return {
        "top_words": [{"word": w, "count": c} for w, c in zip(top["w"], top["len"], strict=True)],
        "vocab_richness": round(unique / total, 4) if total else None,
        "unique_word_count": int(unique),
        "hapax_ratio": round(hapax / unique, 4) if unique else None,
        "zipf_slope": zipf_slope,
    }


def compute_commands(df: pl.DataFrame, top_n: int) -> dict:
    base = (
        df.filter(pl.col("text").str.starts_with("!"))
        .select(
            pl.col("text").str.strip_prefix("!").str.extract(COMMAND_RE, 0).str.to_lowercase().alias("cmd"),
            "user_id",
        )
        .drop_nulls("cmd")
    )

    messages_with_commands = base.height
    top_cmds = (
        base.group_by("cmd")
        .agg(pl.len().alias("count"), pl.col("user_id").n_unique().alias("unique_users"))
        .sort(["count", "cmd"], descending=[True, False])
        .head(top_n)
    )
    return {
        "messages_with_commands": messages_with_commands,
        "top_commands": [
            {"name": n, "count": c, "unique_users": u}
            for n, c, u in zip(top_cmds["cmd"], top_cmds["count"], top_cmds["unique_users"], strict=True)
        ],
    }


def compute_phrases(df: pl.DataFrame, limit: int) -> dict:
    tokens_df = (
        df.select(clean_text_expr().str.extract_all(WORD_RE).alias("t")).filter(pl.col("t").list.len() >= 2)
    )

    bigrams = (
        tokens_df.with_columns(
            pl.col("t").list.slice(0, pl.col("t").list.len() - 1).alias("a"),
            pl.col("t").list.slice(1).alias("b"),
        )
        .explode(["a", "b"])
        .drop_nulls(["a", "b"])
        .select((pl.col("a") + " " + pl.col("b")).alias("phrase"))
        .group_by("phrase")
        .len()
        .filter(pl.col("len") >= 2)
        .sort(["len", "phrase"], descending=[True, False])
        .head(limit)
    )

    return {"top_phrases": [{"phrase": p, "count": c} for p, c in zip(bigrams["phrase"], bigrams["len"], strict=True)]}
