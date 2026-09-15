"""Compact per-channel summaries for multi-channel runs."""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from ..frame import parse_twitch_emotes
from ..models import (
    ChannelSummary,
    CommandCount,
    DayCount,
    DomainCount,
    EmoteCount,
    MentionCount,
    RoleCount,
    TopChatterStat,
    WordCount,
)
from .emotes import count_emotes
from .health import compute_roles
from .links import compute_links
from .mentions import compute_mentions, mention_pairs_frame
from .overview import compute_users
from .temporal import compute_time
from .words import compute_commands, compute_words

# Rows shown in the "side-by-side compare" lists. Frontend slices further.
PER_CHANNEL_LIST_SIZE = 10
CHATTERS_TOP_N = 5
EMOTES_TOP_N = 5


def compute_channel_summary(
    df: pl.DataFrame,
    channel: str,
    emote_map: dict[str, str],
    *,
    stopwords: frozenset[str],
    merged_min_date: date,
    merged_max_date: date,
) -> ChannelSummary:
    """Compute the compact summary for one channel within the merged span.

    `merged_min_date` / `merged_max_date` come from the merged frame's span,
    so this channel's day array aligns to the merged chart even if this
    channel was quiet on some days. Callers skip this when the merged frame
    is empty (there is no span to align to).
    """
    sub = df.filter(pl.col("channel") == channel)
    if sub.is_empty():
        return ChannelSummary(
            channel=channel,
            total_messages=0,
            unique_chatters=0,
            top_chatters=[],
            top_emotes=[],
            top_words=[],
            top_commands=[],
            top_domains=[],
            top_mentions=[],
            roles=[],
            peak_concurrent_chatters=None,
            messages_per_day=_align_days([], merged_min_date, merged_max_date),
            first_message=None,
            last_message=None,
        )

    total = sub.height
    unique_chatters = sub["user_id"].n_unique()
    first_message = sub["ts"].min().isoformat()
    last_message = sub["ts"].max().isoformat()

    users = compute_users(sub, CHATTERS_TOP_N, include_engagement=False)["top_chatters"]
    top_chatters = [TopChatterStat(**u) for u in users]

    twitch_emotes = parse_twitch_emotes(sub)
    top_emotes_raw, _ = count_emotes(sub, twitch_emotes, emote_map, EMOTES_TOP_N)
    top_emotes = [EmoteCount(**e) for e in top_emotes_raw]

    # Side-by-side lists — each is the existing analytics function run against
    # this channel's sub-frame, then capped to PER_CHANNEL_LIST_SIZE.
    words_result = compute_words(sub, stopwords, PER_CHANNEL_LIST_SIZE)
    top_words = [WordCount(**w) for w in words_result["top_words"]]

    commands_result = compute_commands(sub, PER_CHANNEL_LIST_SIZE)
    top_commands = [CommandCount(**c) for c in commands_result["top_commands"]]

    links_result = compute_links(sub, PER_CHANNEL_LIST_SIZE, all_urls_limit=0)
    top_domains = [DomainCount(**d) for d in links_result["top_domains"]]

    mentions_result = compute_mentions(sub, PER_CHANNEL_LIST_SIZE, mention_pairs_frame(sub))
    top_mentions = [MentionCount(**m) for m in mentions_result["top_mentions"]]

    roles_raw = compute_roles(sub)["roles"]
    roles = [RoleCount(**r) for r in roles_raw]

    time_stats = compute_time(sub)
    peak_concurrent = time_stats.get("peak_concurrent_chatters")
    per_day_raw = time_stats["messages_per_day"]

    return ChannelSummary(
        channel=channel,
        total_messages=total,
        unique_chatters=unique_chatters,
        top_chatters=top_chatters,
        top_emotes=top_emotes,
        top_words=top_words,
        top_commands=top_commands,
        top_domains=top_domains,
        top_mentions=top_mentions,
        roles=roles,
        peak_concurrent_chatters=peak_concurrent,
        messages_per_day=_align_days(per_day_raw, merged_min_date, merged_max_date),
        first_message=first_message,
        last_message=last_message,
    )


def _align_days(
    per_day: list[dict],
    merged_min_date: date,
    merged_max_date: date,
) -> list[DayCount]:
    """Pad/trim a channel's per-day counts to the merged window."""
    by_date = {d["date"]: int(d["count"]) for d in per_day}
    out: list[DayCount] = []
    cur = merged_min_date
    while cur <= merged_max_date:
        iso = cur.isoformat()
        out.append(DayCount(date=iso, count=by_date.get(iso, 0)))
        cur += timedelta(days=1)
    return out
