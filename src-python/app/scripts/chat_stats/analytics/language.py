"""Optional language breakdown via langdetect (import-gated)."""
from __future__ import annotations

import random

import polars as pl

from ..constants import LANG_SAMPLE_SIZE, MIN_ALPHA_CHARS_FOR_LANG
from ..frame import clean_text_expr


def detect_language(df: pl.DataFrame) -> list[dict]:
    """Optional basic language breakdown. Requires the ``langdetect`` package."""
    try:
        from langdetect import DetectorFactory, detect  # type: ignore
        from langdetect.lang_detect_exception import LangDetectException  # type: ignore
    except ImportError:
        return []

    # Idempotent and cheap: no lock needed. Two jobs setting the same seed
    # concurrently is harmless.
    DetectorFactory.seed = 0

    cleaned = clean_text_expr(lowercase=False)
    # Keep messages with a meaningful amount of alphabetic content (Unicode-
    # aware) so the detector isn't dominated by emote spam.
    candidates = (
        df.select(cleaned.alias("c"))
        .filter(pl.col("c").str.extract_all(r"\p{L}").list.len() >= MIN_ALPHA_CHARS_FOR_LANG)
        .get_column("c")
        .to_list()
    )
    if not candidates:
        return []

    rng = random.Random(42)
    sample_size = min(LANG_SAMPLE_SIZE, len(candidates))
    sample = rng.sample(candidates, sample_size)

    lang_counts: dict[str, int] = {}
    for text in sample:
        try:
            lang = detect(text)
        except LangDetectException:
            # Undetectable input (too short, emote-only, mixed scripts).
            continue
        lang_counts[lang] = lang_counts.get(lang, 0) + 1

    total = sum(lang_counts.values())
    if total == 0:
        return []

    return [
        {"language": lang, "percentage": round((count / total) * 100, 2)}
        for lang, count in sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)
    ]


def detect_language_by_day(df: pl.DataFrame) -> list[dict]:
    """Top language per day (same sampling as :func:`detect_language`, per day)."""
    try:
        from langdetect import DetectorFactory, detect  # type: ignore
        from langdetect.lang_detect_exception import LangDetectException  # type: ignore
    except ImportError:
        return []

    DetectorFactory.seed = 0
    cleaned = clean_text_expr(lowercase=False)

    # Sample up to LANG_SAMPLE_SIZE messages per day, alphabetic-only.
    candidates = df.select(
        pl.col("ts").dt.date().alias("day"),
        cleaned.alias("c"),
    ).filter(pl.col("c").str.extract_all(r"\p{L}").list.len() >= MIN_ALPHA_CHARS_FOR_LANG)
    if candidates.is_empty():
        return []

    per_day: dict[str, list[str]] = {}
    for day, text in zip(candidates["day"].to_list(), candidates["c"].to_list(), strict=True):
        per_day.setdefault(day.isoformat(), []).append(text)

    out: list[dict] = []
    for day, texts in sorted(per_day.items()):
        # Seed derived from the day itself (string seeds are deterministic
        # across runs, unlike hash()): each day draws from its own stream,
        # so adding/removing day 0 never reshuffles every later dot — while
        # two days with equal-sized pools no longer mirror each other.
        day_rng = random.Random(f"langday:{day}")
        sample = day_rng.sample(texts, min(LANG_SAMPLE_SIZE, len(texts)))
        lang_counts: dict[str, int] = {}
        for t in sample:
            try:
                lang = detect(t)
            except LangDetectException:
                continue
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
        total = sum(lang_counts.values())
        if total == 0:
            continue
        top_lang, top_count = max(lang_counts.items(), key=lambda kv: kv[1])
        out.append(
            {
                "date": day,
                "language": top_lang,
                "percentage": round(top_count / total * 100, 2),
            }
        )
    return out
