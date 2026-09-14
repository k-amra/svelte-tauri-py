"""Chat-health analytics: duplicates, roles, repetition, copypasta, non-ASCII."""
from __future__ import annotations

import polars as pl

from ..constants import (
    COPY_PASTE_MIN_OCCURRENCES,
    COPY_PASTE_TOP_N,
    COPY_PASTE_WINDOW_S,
    EMOTE_TOKEN_RE,
    MAX_REPEAT_TEXT_LEN,
    MENTION_RE,
    MIN_ALPHA_FOR_CAPS,
    URL_RE,
)


def compute_health(df: pl.DataFrame, top_n: int) -> dict:
    # len_chars is functionally determined by text; grouping by both is redundant.
    dupes = (
        df.group_by("text")
        .agg(
            pl.len().alias("len"),
            pl.col("text").str.len_chars().first().alias("len_chars"),
        )
        .filter(pl.col("len") > 1)
    )
    dup_sum = dupes.select((pl.col("len") - 1).sum()).item() if not dupes.is_empty() else None
    duplicate_message_count = int(dup_sum) if dup_sum is not None else 0

    top_reps = dupes.sort(["len", "text"], descending=[True, False]).head(top_n)
    top_repeated_messages = []
    for text, count, length in zip(top_reps["text"], top_reps["len"], top_reps["len_chars"], strict=True):
        text_val = text if length <= MAX_REPEAT_TEXT_LEN else text[:MAX_REPEAT_TEXT_LEN] + "..."
        top_repeated_messages.append({"text": text_val, "count": count})

    return {
        "duplicate_message_count": duplicate_message_count,
        "top_repeated_messages": top_repeated_messages,
    }


def compute_roles(df: pl.DataFrame) -> dict:
    roles = df.group_by("role").agg(
        pl.len().alias("messages"),
        pl.col("user_id").n_unique().alias("unique_users"),
    )
    return {
        "roles": [
            {"role": r, "messages": m, "unique_users": u}
            for r, m, u in zip(roles["role"], roles["messages"], roles["unique_users"], strict=True)
        ]
    }


_STAFF_ROLES = ("broadcaster", "moderator", "vip")
_SUBSCRIBER_ROLES = ("subscriber",)


def _compute_role_roster(df: pl.DataFrame, roles: tuple[str, ...]) -> list[dict]:
    """Shared implementation: one row per user ever seen with one of `roles`.

    messageCount covers ALL of that user's messages in range (not just the
    ones where the badge was present). Role is the chronologically last role
    the user held among `roles` (frame is sorted by ts, so `.last()` over the
    filtered frame is correct).
    """
    if df.height == 0 or "role" not in df.columns:
        return []

    counts = df.group_by("user_id").agg(
        pl.col("username").last().alias("username"),
        pl.col("ts").min().alias("firstSeen"),
        pl.col("ts").max().alias("lastSeen"),
        pl.len().alias("totalMessages"),
    )
    roles_observed = (
        df.filter(pl.col("role").is_in(roles))
        .group_by("user_id")
        .agg(pl.col("role").last().alias("role"))
    )
    grouped = counts.join(roles_observed, on="user_id", how="inner").sort(
        ["role", "totalMessages", "user_id"],
        descending=[False, True, False],
    )
    return [
        {
            "user_id": r["user_id"],
            "username": r["username"],
            "role": r["role"],
            "messageCount": int(r["totalMessages"]),
            "firstSeen": r["firstSeen"].isoformat() if r["firstSeen"] else None,
            "lastSeen": r["lastSeen"].isoformat() if r["lastSeen"] else None,
        }
        for r in grouped.iter_rows(named=True)
    ]


def compute_staff_list(df: pl.DataFrame) -> dict:
    """Per-user list of broadcaster, moderators, and VIPs (see `_compute_role_roster`).

    Staff who sent zero messages in the range cannot appear: roles are only
    observable on messages, and upstream exposes no channel roster.
    """
    return {"staff_list": _compute_role_roster(df, _STAFF_ROLES)}


def compute_subscriber_list(df: pl.DataFrame, top_n: int = 200) -> dict:
    """Per-user list of subscribers, capped at `top_n`.

    Returns `subscriber_count` (the true distinct-subscriber count, which the
    UI can display even when the list is truncated) alongside the capped list.
    """
    rows = _compute_role_roster(df, _SUBSCRIBER_ROLES)
    return {"subscriber_list": rows[:top_n], "subscriber_count": len(rows)}


def compute_self_repetition(df: pl.DataFrame) -> dict:
    """Same user sending the identical text twice in a row (per-user sequence)."""
    if df.height < 2:
        return {"self_repetition_count": 0, "self_repetition_pct": None}

    s = df.select("user_id", "text", "ts").sort("user_id", "ts")
    s = s.with_columns(
        (
            (pl.col("user_id") == pl.col("user_id").shift(1))
            & (pl.col("text") == pl.col("text").shift(1))
        )
        .fill_null(False)
        .alias("is_repeat")
    )
    count = int(s["is_repeat"].sum())
    total = df.height
    return {
        "self_repetition_count": count,
        "self_repetition_pct": round(count / total * 100, 2) if total else None,
    }


def compute_copy_paste_chains(df: pl.DataFrame) -> dict:
    """Same text reposted by *different* users within a short window (raids/copypasta).

    ``cross_user_copy_paste_count`` counts chain *events* (inter-user
    handoffs: five users reposting in sequence is four events), while
    ``cross_user_copy_paste_texts`` counts distinct texts with >= 1 event.
    """
    if df.height < COPY_PASTE_MIN_OCCURRENCES:
        return {
            "cross_user_copy_paste_count": 0,
            "cross_user_copy_paste_texts": 0,
            "top_copy_paste_chains": [],
        }

    # Only texts that appear >= N times across >= 2 users are candidates.
    # This keeps the join bounded even for channels with heavy spam.
    candidate_texts = (
        df.group_by("text")
        .agg(pl.len().alias("n"), pl.col("user_id").n_unique().alias("u"))
        .filter((pl.col("n") >= COPY_PASTE_MIN_OCCURRENCES) & (pl.col("u") >= 2))
    )
    if candidate_texts.is_empty():
        return {
            "cross_user_copy_paste_count": 0,
            "cross_user_copy_paste_texts": 0,
            "top_copy_paste_chains": [],
        }

    candidates = (
        df.join(candidate_texts.select("text"), on="text", how="inner")
        .select("text", "user_id", "ts")
        .sort(["text", "ts"])
        .with_columns(
            [
                pl.col("user_id").shift(1).over("text").alias("prev_user"),
                pl.col("ts").shift(1).over("text").alias("prev_ts"),
            ]
        )
    )

    # A chain event: consecutive same-text messages by *different* users
    # within the window.
    chains = candidates.filter(
        pl.col("prev_user").is_not_null()
        & (pl.col("user_id") != pl.col("prev_user"))
        & ((pl.col("ts") - pl.col("prev_ts")).dt.total_seconds() <= COPY_PASTE_WINDOW_S)
    )

    # Distinct participants include the originator (present only as prev_user
    # on the first event), so union both sides rather than counting reposters.
    distinct_users = (
        chains.select("text", "user_id")
        .vstack(chains.select("text", pl.col("prev_user").alias("user_id")).drop_nulls("user_id"))
        .group_by("text")
        .agg(pl.col("user_id").n_unique().alias("distinct_users"))
    )
    top = (
        chains.group_by("text")
        .agg(pl.len().alias("occurrences"))
        .join(distinct_users, on="text", how="left")
        .sort(["occurrences", "text"], descending=[True, False])
        .head(COPY_PASTE_TOP_N)
    )

    return {
        "cross_user_copy_paste_count": chains.height,
        "cross_user_copy_paste_texts": chains.select("text").n_unique(),
        "top_copy_paste_chains": [
            {"text": t[:200], "occurrences": int(o), "distinct_users": int(u)}
            for t, o, u in zip(top["text"], top["occurrences"], top["distinct_users"], strict=True)
        ],
    }


def compute_non_ascii(df: pl.DataFrame) -> dict:
    """Share of non-ASCII characters (raid/audience-shift signal)."""
    if df.height == 0:
        return {"non_ascii_ratio": None, "messages_with_non_ascii": 0}

    per_msg = df.select(
        pl.col("text").str.extract_all(r"\P{ASCII}").list.len().alias("non_ascii"),
        pl.col("text").str.len_chars().alias("len_chars"),
    )

    total_chars = int(per_msg["len_chars"].sum())
    non_ascii_chars = int(per_msg["non_ascii"].sum())
    messages_with = int(per_msg.filter(pl.col("non_ascii") > 0).height)

    return {
        "non_ascii_ratio": round(non_ascii_chars / total_chars, 4) if total_chars else None,
        "messages_with_non_ascii": messages_with,
    }


def compute_message_classes(
    df: pl.DataFrame, twitch_emotes: pl.Series, emote_map: dict[str, str]
) -> dict:
    """Message-shape buckets. NOTE: meaningful `emote_only` numbers need a
    non-empty `emote_map` (third-party catalog) and/or Twitch `emotes` tags —
    with both empty every message trivially has no known emotes."""
    txt = pl.col("text")
    r = txt.str.strip_chars_end()

    # Unicode-aware so Polish/Cyrillic/etc. aren't miscounted as non-letters.
    alpha_count = txt.str.extract_all(r"\p{L}").list.len()
    upper_count = txt.str.extract_all(r"\p{Lu}").list.len()

    # Gather all known emote names once (third-party catalog values + Twitch
    # names) so a message that is *only* emotes can be identified.
    known_emotes_lower: set[str] = {v.lower() for v in emote_map.values()}
    if not twitch_emotes.is_empty():
        twitch_names = twitch_emotes.explode(empty_as_null=True).drop_nulls().unique().to_list()
        known_emotes_lower.update(str(n).lower() for n in twitch_names)

    words = (
        txt.str.replace_all(URL_RE, " ")
        .str.replace_all(MENTION_RE, " ")
        .str.extract_all(EMOTE_TOKEN_RE)
        .list.eval(pl.element().str.to_lowercase())
    )

    if known_emotes_lower:
        # `is_in` accepts a Series/list; a set happens to work today but
        # isn't documented. Match the `list(stopwords)` style used elsewhere.
        known_emotes_list = list(known_emotes_lower)
        non_emote_words = (
            words.list.eval(pl.element().filter(~pl.element().is_in(known_emotes_list))).list.len()
        )
    else:
        non_emote_words = words.list.len()

    has_twitch_emote = twitch_emotes.list.len() > 0
    has_3rd_party_emote = words.list.len() > non_emote_words
    has_any_emote = has_twitch_emote | has_3rd_party_emote

    # One pass: build boolean masks per class, then sum. Each `.sum()` on a
    # Boolean column is an integer count of the True rows.
    counts = df.select(
        r.str.ends_with("?").sum().alias("questions"),
        r.str.ends_with("!").sum().alias("exclamations"),
        (txt.str.len_chars() <= 3).sum().alias("short_messages"),
        (txt.str.len_chars() >= 200).sum().alias("long_messages"),
        ((alpha_count >= MIN_ALPHA_FOR_CAPS) & (upper_count >= (alpha_count * 0.8)))
            .sum()
            .alias("all_caps"),
        (has_any_emote & (non_emote_words == 0)).sum().alias("emote_only"),
    )

    return {
        "message_classes": {
            "questions": int(counts["questions"][0]),
            "exclamations": int(counts["exclamations"][0]),
            "all_caps": int(counts["all_caps"][0]),
            "emote_only": int(counts["emote_only"][0]),
            "short_messages": int(counts["short_messages"][0]),
            "long_messages": int(counts["long_messages"][0]),
        }
    }
