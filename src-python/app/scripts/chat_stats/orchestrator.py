"""compute_stats entry point: runs each analytics module in order."""
from __future__ import annotations

import polars as pl

from .analytics.anomalies import detect_anomalies
from .analytics.bots import compute_bot_scores
from .analytics.cohorts import compute_cohort_retention
from .analytics.concentration import compute_concentration, compute_lorenz
from .analytics.emotes import (
    compute_emote_centrality,
    compute_emote_diversity,
    compute_emote_entropy,
    compute_emote_pairs,
    count_emotes,
    emote_pairs_frame,
)
from .analytics.health import (
    compute_copy_paste_chains,
    compute_health,
    compute_message_classes,
    compute_non_ascii,
    compute_roles,
    compute_self_repetition,
)
from .analytics.language import detect_language, detect_language_by_day
from .analytics.length import compute_length_trend
from .analytics.links import compute_links
from .analytics.mentions import (
    compute_mention_graph,
    compute_mentions,
    compute_mutual_mentions,
    compute_quote_replies,
    mention_pairs_frame,
)
from .analytics.overview import (
    compute_activity_per_day,
    compute_chatter_dist,
    compute_overview,
    compute_users,
)
from .analytics.sessions import compute_sessions
from .analytics.temporal import (
    compute_first_message_hours,
    compute_new_returning,
    compute_time,
)
from .analytics.words import compute_commands, compute_phrases, compute_words
from .constants import (
    MAX_PLAUSIBLE_AVG_MESSAGE_LEN,
    MIN_PLAUSIBLE_AVG_MESSAGE_LEN,
    STOPWORDS,
)
from .frame import parse_twitch_emotes
from .models import Params, Result


def compute_stats(df: pl.DataFrame, params: Params, emote_map: dict[str, str]) -> dict:
    if df.is_empty():
        # Let Pydantic defaults fill everything except required fields.
        return Result(
            total_messages=0,
            unique_chatters=0,
            days_spanned=0,
            avg_message_length=0.0,
            truncated=False,
            top_chatters=[],
            activity_by_hour=[0] * 24,
            activity_by_weekday_hour=[[0] * 24 for _ in range(7)],
            messages_per_day=[],
            top_words=[],
            top_emotes=[],
        ).model_dump()

    # Optional single-user filter: run BEFORE any analytics so every downstream
    # module sees a frame that is already scoped. Empirically this is one
    # vectorized pass (~ms on 100k rows); the on-disk channel cache is shared
    # with whole-channel runs, so no extra network cost.
    if params.user is not None:
        target = params.user.strip()
        if params.user_id_type == "userid":
            df = df.filter(pl.col("user_id") == target)
        else:
            # Usernames are stored exactly as upstream returns them; match
            # case-insensitively so "Bob" and "bob" both hit.
            df = df.filter(pl.col("username").str.to_lowercase() == target.lower())

        # If the filter matched nothing, emit the same empty-result shape
        # the caller would see for an empty channel.
        if df.is_empty():
            return Result(
                total_messages=0,
                unique_chatters=0,
                days_spanned=0,
                avg_message_length=0.0,
                truncated=False,
                top_chatters=[],
                activity_by_hour=[0] * 24,
                activity_by_weekday_hour=[[0] * 24 for _ in range(7)],
                messages_per_day=[],
                top_words=[],
                top_emotes=[],
            ).model_dump()

    # Parse emotes once; both top emotes and co-occurrence pairs use this.
    twitch_emotes = parse_twitch_emotes(df)

    stats: dict = {}
    stats.update(compute_overview(df))
    stats.update(compute_users(df, params.top_n, params.include_engagement))
    stats.update(compute_chatter_dist(df))
    stats.update(compute_activity_per_day(df))
    stats.update(compute_time(df))
    stats.update(compute_roles(df))
    stats.update(compute_first_message_hours(df))

    top_emotes, seen_emotes = count_emotes(df, twitch_emotes, emote_map, params.top_emotes_n)
    stats["top_emotes"] = top_emotes

    # Build the emote-pairs frame once, feed both consumers.
    if params.include_emote_pairs or params.include_emote_centrality:
        emote_pairs = emote_pairs_frame(twitch_emotes)
    else:
        emote_pairs = None

    if params.include_emote_pairs and emote_pairs is not None:
        stats["top_emote_pairs"] = compute_emote_pairs(emote_pairs, params.top_n)
    if params.include_emote_centrality and emote_pairs is not None:
        stats.update(compute_emote_centrality(emote_pairs, params.top_n))
    if params.include_emote_entropy:
        stats.update(compute_emote_entropy(twitch_emotes))

    stats.update(compute_emote_diversity(df, twitch_emotes, params.top_n))

    stopwords = STOPWORDS | {name.lower() for name in seen_emotes}
    stats.update(compute_words(df, stopwords, params.top_words_n))

    stats.update(compute_non_ascii(df))
    stats.update(compute_self_repetition(df))

    if params.include_commands:
        stats.update(compute_commands(df, params.top_n))
    if params.include_links:
        stats.update(compute_links(df, params.top_n))

    # Mention frame once, feed three consumers.
    if params.include_mentions or params.include_mention_graph or params.include_mutual_mentions:
        mention_pairs = mention_pairs_frame(df)
    else:
        mention_pairs = None

    if params.include_mentions and mention_pairs is not None:
        stats.update(compute_mentions(df, params.top_n, mention_pairs))
    if params.include_mention_graph and mention_pairs is not None:
        stats.update(compute_mention_graph(mention_pairs, params.top_n))
    if params.include_mutual_mentions and mention_pairs is not None:
        stats.update(compute_mutual_mentions(mention_pairs, params.top_n))

    if params.include_duplicates:
        stats.update(compute_health(df, params.top_n))
    if params.include_sessions:
        stats.update(compute_sessions(df, params.session_gap_minutes))
    if params.include_concentration:
        stats.update(compute_concentration(df))
    if params.include_lorenz:
        stats.update(compute_lorenz(df))
    if params.include_message_class:
        stats.update(compute_message_classes(df, twitch_emotes, emote_map))
    if params.include_phrases:
        stats.update(compute_phrases(df, params.top_phrases_n))
    if params.include_new_returning:
        stats.update(compute_new_returning(df))
    if params.include_anomalies:
        stats["anomalies_5m"] = detect_anomalies(df, params.anomaly_sigma)
    if params.include_language:
        stats["language_breakdown"] = detect_language(df)
    if params.include_language and params.include_language_by_day:
        stats["language_by_day"] = detect_language_by_day(df)
    if params.include_copy_paste_chains:
        stats.update(compute_copy_paste_chains(df))
    if params.include_length_trend:
        stats.update(compute_length_trend(df))
    if params.include_cohort_retention:
        stats.update(compute_cohort_retention(df))
    if params.include_bot_scores:
        stats.update(compute_bot_scores(df))
    if params.include_quote_replies:
        stats.update(compute_quote_replies(df))

    stats["warnings"] = _sanity_warnings(df, stats)
    return stats


def _sanity_warnings(df: pl.DataFrame, stats: dict) -> list[str]:
    """Data-quality flags: cheap cross-checks over the finished stats."""
    w: list[str] = []
    if df.height == 0:
        return w

    avg_len = stats.get("avg_message_length")
    if avg_len is not None:
        if avg_len < MIN_PLAUSIBLE_AVG_MESSAGE_LEN:
            w.append(
                f"avg_message_length={avg_len:.2f} is implausibly small; "
                "upstream may be truncating text."
            )
        if avg_len > MAX_PLAUSIBLE_AVG_MESSAGE_LEN:
            w.append(
                f"avg_message_length={avg_len:.2f} is implausibly large; "
                "check for merged messages upstream."
            )

    # messages_per_day should span the same day count as days_spanned.
    mpd = stats.get("messages_per_day") or []
    spanned = stats.get("days_spanned")
    if spanned is not None and mpd and len(mpd) != spanned:
        w.append(
            f"messages_per_day has {len(mpd)} entries but days_spanned={spanned}; "
            "gaps in the range may be missing from the cache."
        )

    # Every hourly bucket should sum to total_messages.
    hourly = stats.get("activity_by_hour")
    total = stats.get("total_messages")
    if hourly is not None and total is not None and sum(hourly) != total:
        w.append(f"activity_by_hour sums to {sum(hourly)} but total_messages={total}.")

    empty = int((df["text"].str.len_chars() == 0).sum())
    if empty > 0:
        w.append(f"{empty} messages have empty text — likely upstream dropouts.")

    if df.height >= 2:
        ts = df["ts"]
        if (ts.diff().dt.total_seconds() < 0).any():
            w.append("timestamps are not monotonic; cache merge may have reordered rows.")

    return w
