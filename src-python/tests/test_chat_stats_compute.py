"""Unit tests for the pure analytics layer (no network)."""

from datetime import UTC, datetime, timedelta

import polars as pl

from app.scripts import chat_stats as cs
from app.services.harambelogs_models import FullMessage

UTC = UTC
TS = pl.Datetime(time_unit="us", time_zone="UTC")


def make_params(**overrides) -> cs.Params:
    base: dict = {
        "channel": "chan",
        "from_date": datetime(2024, 1, 1, tzinfo=UTC),
        "to_date": datetime(2024, 1, 31, tzinfo=UTC),
    }
    base.update(overrides)
    return cs.Params(**base)


def make_frame(rows: list[tuple[str, str, datetime]]) -> pl.DataFrame:
    """Build a full-schema frame (user_id/role/emotes_tag/id) like messages_to_frame."""
    usernames, texts, stamps = zip(*rows, strict=True)
    n = len(rows)
    return pl.DataFrame(
        {
            "user_id": list(usernames),
            "username": list(usernames),
            "text": list(texts),
            "ts": pl.Series(list(stamps), dtype=TS),
            "emotes_tag": [None] * n,
            "id": [str(i) for i in range(n)],
            "role": ["regular"] * n,
        }
    ).sort("ts")


def msg(username: str, text: str, ts: datetime) -> FullMessage:
    return FullMessage(
        type=1,
        text=text,
        displayName=username,
        timestamp=ts,
        id="1",
        tags={},
        username=username,
        channel="chan",
        raw=text,
    )


def test_counts_and_top_n_capping():
    rows = (
        [("a", "hello world", datetime(2024, 1, 15, 10, 0, tzinfo=UTC))] * 15
        + [("b", "hi there", datetime(2024, 1, 15, 11, 0, tzinfo=UTC))] * 10
        + [("c", "yo", datetime(2024, 1, 16, 12, 0, tzinfo=UTC))] * 5
        + [("d", "hey", datetime(2024, 1, 16, 12, 0, tzinfo=UTC))] * 4
        + [("e", "sup", datetime(2024, 1, 16, 12, 0, tzinfo=UTC))] * 3
        + [("f", "lol", datetime(2024, 1, 16, 12, 0, tzinfo=UTC))] * 2
        + [("g", "omg", datetime(2024, 1, 16, 12, 0, tzinfo=UTC))] * 1
    )
    stats = cs.compute_stats(make_frame(rows), make_params(top_n=5), {})
    assert stats["total_messages"] == 40
    assert stats["unique_chatters"] == 7
    assert stats["days_spanned"] == 2
    assert [t["username"] for t in stats["top_chatters"]] == ["a", "b", "c", "d", "e"]
    assert stats["top_chatters"][0]["messageCount"] == 15
    assert stats["top_chatters"][0]["user_id"] == "a"
    assert stats["top_chatters"][0]["activeDays"] >= 1
    assert stats["activity_by_hour"][10] == 15
    assert stats["activity_by_hour"][11] == 10
    assert stats["activity_by_hour"][12] == 15
    assert stats["messages_per_day"] == [
        {"date": "2024-01-15", "count": 25},
        {"date": "2024-01-16", "count": 15},
    ]


def test_heatmap_shape_and_monday_placement():
    # 2024-01-15 is a Monday; 2024-01-21 is a Sunday.
    rows = [
        ("a", "hello", datetime(2024, 1, 15, 10, 30, tzinfo=UTC)),
        ("b", "world hello", datetime(2024, 1, 21, 23, 0, tzinfo=UTC)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(top_n=20), {})
    heat = stats["activity_by_weekday_hour"]
    assert len(heat) == 7 and all(len(row) == 24 for row in heat)
    assert heat[0][10] == 1  # Monday 10:00 UTC
    assert heat[6][23] == 1  # Sunday 23:00 UTC
    assert sum(sum(row) for row in heat) == 2


def test_top_words_filters_stopwords_and_short_tokens():
    rows = [
        ("a", "Hello hello the a x PogChamp", datetime(2024, 1, 15, 10, 0, tzinfo=UTC)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(top_n=20), {})
    words = {w["word"]: w["count"] for w in stats["top_words"]}
    assert words.get("hello") == 2
    assert "pogchamp" in words
    assert "the" not in words  # stopword
    assert "a" not in words  # single char + stopword
    assert "x" not in words  # single char
    assert stats["avg_message_length"] == len("Hello hello the a x PogChamp")


def test_catalog_emote_names_excluded_from_top_words():
    rows = [
        ("a", "Kappa hello world", datetime(2024, 1, 15, 10, 0, tzinfo=UTC)),
        ("b", "KEKW hello", datetime(2024, 1, 15, 11, 0, tzinfo=UTC)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(top_n=20), {"25": "Kappa", "b1": "KEKW"})
    words = {w["word"]: w["count"] for w in stats["top_words"]}
    assert "kappa" not in words
    assert "kekw" not in words
    assert words.get("hello") == 2
    assert words.get("world") == 1


def test_native_emote_names_excluded_from_top_words():
    # Twitch-native emotes travel in the IRC tag; their names must not leak
    # into the vocabulary stats even without a third-party catalog entry.
    good = FullMessage(
        type=1,
        text="Kappa hello",
        displayName="a",
        timestamp=datetime(2024, 1, 15, 10, 0, tzinfo=UTC),
        id="1",
        tags={"emotes": "25:0-4"},
        username="a",
        channel="chan",
        raw="Kappa hello",
    )
    df = cs.messages_to_frame([good])
    stats = cs.compute_stats(df, make_params(), {})
    words = {w["word"] for w in stats["top_words"]}
    assert "kappa" not in words
    assert "hello" in words


def test_emote_only_uses_twitch_tag_names():
    tagged = FullMessage(
        type=1,
        text="Kappa Kappa",
        displayName="a",
        timestamp=datetime(2024, 1, 15, 10, 0, tzinfo=UTC),
        id="1",
        tags={"emotes": "25:0-4,6-10"},
        username="a",
        channel="chan",
        raw="Kappa Kappa",
    )
    df = cs.messages_to_frame([tagged, msg("b", "hello world", datetime(2024, 1, 15, 11, 0, tzinfo=UTC))])
    stats = cs.compute_stats(df, make_params(), {})
    assert stats["message_classes"]["emote_only"] == 1


def test_empty_frame_returns_zeroed_shapes():
    stats = cs.compute_stats(cs.messages_to_frame([]), make_params(top_n=20), {})
    assert stats["total_messages"] == 0
    assert stats["unique_chatters"] == 0
    assert stats["days_spanned"] == 0
    assert stats["avg_message_length"] == 0.0
    assert stats["top_chatters"] == []
    assert stats["activity_by_hour"] == [0] * 24
    assert stats["activity_by_weekday_hour"] == [[0] * 24 for _ in range(7)]
    assert stats["messages_per_day"] == []
    assert stats["top_words"] == []
    assert stats["top_emotes"] == []


def test_messages_to_frame_parses_iso_and_drops_garbage():
    good = msg("a", "hi", datetime(2024, 1, 15, 10, 0, tzinfo=UTC))
    naive = msg("b", "yo", datetime(2024, 1, 15, 11, 0))  # naive → assumed UTC
    bad = FullMessage.model_construct(
        username="c", text="junk", timestamp="not-a-date", channel="chan"
    )
    df = cs.messages_to_frame([good, naive, bad])
    assert df.height == 2
    assert sorted(df["username"].to_list()) == ["a", "b"]
    assert df["ts"].dtype == TS
    assert "user_id" in df.columns
    assert "role" in df.columns
    assert "id" in df.columns


def test_clean_text_expr_strips_urls_and_mentions():
    df = pl.DataFrame({"text": ["hey @alice check https://example.com/x KEEP"]})
    lowered = df.select(cs._clean_text_expr().alias("c"))["c"].to_list()
    assert lowered == ["hey   check   keep"]
    cased = df.select(cs._clean_text_expr(lowercase=False).alias("c"))["c"].to_list()
    assert cased == ["hey   check   KEEP"]


def test_messages_to_frame_empty_dtypes_match_non_empty():
    full = cs.messages_to_frame([msg("a", "hi", datetime(2024, 1, 15, 10, 0, tzinfo=UTC))])
    empty = cs.messages_to_frame([])
    assert full.schema == empty.schema


def test_overview_includes_medians_and_roles():
    rows = [
        ("a", "hi", datetime(2024, 1, 15, 10, 0, tzinfo=UTC)),
        ("b", "hello world foo bar", datetime(2024, 1, 15, 11, 0, tzinfo=UTC)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(), {})
    assert stats["median_message_length"] is not None
    assert stats["max_message_length"] is not None
    assert stats["avg_words_per_message"] is not None
    assert isinstance(stats["roles"], list)
    assert stats["top_peaks_5m"] is not None


def test_commands_links_mentions_and_health():
    rows = [
        ("a", "!shoutout hello @bob https://example.com/x", datetime(2024, 1, 15, 10, 0, tzinfo=UTC)),
        ("b", "!shoutout again @bob https://example.com/y", datetime(2024, 1, 15, 10, 1, tzinfo=UTC)),
        ("a", "!shoutout hello @bob https://example.com/x", datetime(2024, 1, 15, 10, 2, tzinfo=UTC)),
    ]
    params = make_params(
        include_commands=True,
        include_links=True,
        include_mentions=True,
        include_duplicates=True,
    )
    stats = cs.compute_stats(make_frame(rows), params, {})
    assert stats["messages_with_commands"] == 3
    assert stats["top_commands"][0]["name"] == "shoutout"
    assert stats["messages_with_links"] == 3
    assert any(d["domain"] == "example.com" for d in stats["top_domains"])
    assert stats["messages_with_mentions"] == 3
    assert stats["duplicate_message_count"] >= 1


def test_self_repetition_counts_same_user_repeats_only():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [
        ("a", "hi", base),
        ("a", "hi", base + timedelta(minutes=1)),
        ("b", "hi", base + timedelta(minutes=2)),
        ("b", "yo", base + timedelta(minutes=3)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(), {})
    assert stats["self_repetition_count"] == 1
    assert stats["self_repetition_pct"] == 25.0


def test_copy_paste_requires_different_users():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [("a", "spam spam", base + timedelta(seconds=10 * i)) for i in range(3)]
    stats = cs.compute_stats(make_frame(rows), make_params(), {})
    assert stats["cross_user_copy_paste_count"] == 0
    assert stats["cross_user_copy_paste_texts"] == 0
    assert stats["top_copy_paste_chains"] == []


def test_copy_paste_counts_cross_user_reposts_in_window():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [
        ("a", "raid incoming", base),
        ("b", "raid incoming", base + timedelta(seconds=20)),
        ("c", "raid incoming", base + timedelta(seconds=40)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(), {})
    assert stats["cross_user_copy_paste_count"] == 2
    assert stats["cross_user_copy_paste_texts"] == 1
    assert stats["top_copy_paste_chains"] == [
        {"text": "raid incoming", "occurrences": 2, "distinct_users": 3}
    ]


def test_copy_paste_window_boundary_excluded():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [
        ("a", "raid incoming", base + timedelta(seconds=61 * i)) for i in range(4)
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(), {})
    assert stats["cross_user_copy_paste_count"] == 0
    assert stats["cross_user_copy_paste_texts"] == 0
    assert stats["top_copy_paste_chains"] == []


def test_peak_concurrent_chatters():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [
        ("a", "one", base),
        ("b", "two", base + timedelta(minutes=1)),
        ("c", "three", base + timedelta(minutes=2)),
        ("d", "lonely", base + timedelta(hours=1)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(), {})
    assert stats["peak_concurrent_chatters"] == 3
    assert stats["peak_concurrent_window"] == "2024-01-15T10:00:00+00:00"


def test_vocab_richness_and_unique_words():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [
        ("a", "alpha beta gamma", base),
        ("b", "alpha beta gamma", base + timedelta(minutes=1)),
        ("c", "alpha", base + timedelta(minutes=2)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(), {})
    assert stats["unique_word_count"] == 3
    assert stats["vocab_richness"] == round(3 / 7, 4)


def test_emote_diversity_per_user():
    def tagged(mid: str, user: str, text: str, tag: str, ts: datetime) -> FullMessage:
        return FullMessage(
            type=1,
            text=text,
            displayName=user,
            timestamp=ts,
            id=mid,
            tags={"emotes": tag},
            username=user,
            channel="chan",
            raw=text,
        )

    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    msgs = [
        tagged(f"a{i}", "a", "Kappa", "25:0-4", base + timedelta(seconds=i)) for i in range(4)
    ] + [
        tagged(f"b{i}", "a", "Keepo", "1902:0-4", base + timedelta(seconds=10 + i)) for i in range(2)
    ]
    msgs.append(tagged("c0", "b", "Kappa", "25:0-4", base + timedelta(minutes=5)))
    df = cs.messages_to_frame(msgs)
    stats = cs.compute_stats(df, make_params(), {})
    assert stats["emote_diversity"] == [
        {
            "user_id": "a",
            "username": "a",
            "total_emote_uses": 6,
            "unique_emotes": 2,
            "diversity_ratio": round(2 / 6, 4),
        }
    ]


def test_non_ascii_ratio():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [
        ("a", "hello", base),
        ("b", "zażółć", base + timedelta(minutes=1)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(), {})
    assert stats["messages_with_non_ascii"] == 1
    assert stats["non_ascii_ratio"] == round(4 / 11, 4)


def test_first_message_hours():
    rows = [
        ("a", "morning", datetime(2024, 1, 15, 10, 5, tzinfo=UTC)),
        ("a", "again", datetime(2024, 1, 15, 11, 0, tzinfo=UTC)),
        ("b", "night", datetime(2024, 1, 15, 23, 30, tzinfo=UTC)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(), {})
    hours = stats["first_message_hours"]
    assert len(hours) == 24
    assert hours[10] == 1
    assert hours[23] == 1
    assert sum(hours) == 2


def test_session_distribution_and_chatter_p99():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [
        ("a", "one", base),
        ("a", "two", base + timedelta(minutes=5)),
        ("a", "later", base + timedelta(hours=2)),
        ("b", "solo", base + timedelta(minutes=30)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(), {})
    sessions = stats["sessions"]
    assert sessions["total_sessions"] == 3
    assert sessions["median_session_minutes"] == 0.0
    # Nearest-rank quantile (same convention as chatter quantiles).
    assert sessions["p90_session_minutes"] == 5.0
    assert stats["chatter_message_quantiles"]["p99"] == 3.0


def _mention_frame(rows: list[tuple[str, str, datetime]]) -> dict:
    return cs.compute_stats(make_frame(rows), make_params(include_mention_graph=True), {})


def test_mention_graph_full_join_symmetric():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [
        ("A", "@Bob hello", base),
        ("A", "@Bob again", base + timedelta(minutes=1)),
        ("B", "nothing here", base + timedelta(minutes=2)),
        ("C", "@Alice yo", base + timedelta(minutes=3)),
    ]
    stats = _mention_frame(rows)
    # Source-only and target-only users get 0 (not null) on the missing side.
    assert stats["mention_graph"] == [
        {"username": "a", "mentions_in": 0, "mentions_out": 2, "degree": 2},
        {"username": "bob", "mentions_in": 2, "mentions_out": 0, "degree": 2},
        {"username": "alice", "mentions_in": 1, "mentions_out": 0, "degree": 1},
        {"username": "c", "mentions_in": 0, "mentions_out": 1, "degree": 1},
    ]


def test_mutual_mentions_keeps_one_direction():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [
        ("a", "@b one", base),
        ("a", "@b two", base + timedelta(minutes=1)),
        ("b", "@a hey", base + timedelta(minutes=2)),
        ("c", "@d solo", base + timedelta(minutes=3)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(include_mutual_mentions=True), {})
    assert stats["mutual_mention_pairs"] == [
        {"user_a": "a", "user_b": "b", "count_ab": 2, "count_ba": 1, "total": 3}
    ]


def test_self_mention_excluded_from_top_but_counted():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [
        ("a", "@a talking to myself", base),
        ("b", "hi @a", base + timedelta(minutes=1)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(), {})
    assert stats["messages_with_mentions"] == 2
    assert stats["top_mentions"] == [{"username": "a", "count": 1}]
    assert stats["top_mention_pairs"] == [{"from_user": "b", "to_user": "a", "count": 1}]


def test_emote_centrality_counts_distinct_partners():
    def tagged(mid: str, text: str, tag: str, ts: datetime) -> FullMessage:
        return FullMessage(
            type=1, text=text, displayName="a", timestamp=ts, id=mid,
            tags={"emotes": tag}, username="a", channel="chan", raw=text,
        )

    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    msgs = [
        tagged("m1", "Kappa Keepo", "25:0-4/1902:6-10", base),
        tagged("m2", "Kappa Keepo", "25:0-4/1902:6-10", base + timedelta(minutes=1)),
    ]
    stats = cs.compute_stats(
        cs.messages_to_frame(msgs), make_params(include_emote_centrality=True), {}
    )
    # Degree (distinct partners), not co-occurrence count.
    assert stats["emote_centrality"] == [
        {"emote": "Kappa", "distinct_co_occurrences": 1},
        {"emote": "Keepo", "distinct_co_occurrences": 1},
    ]


def test_emote_entropy_uniform_vs_dominated():
    def tagged(mid: str, text: str, tag: str, ts: datetime) -> FullMessage:
        return FullMessage(
            type=1, text=text, displayName="a", timestamp=ts, id=mid,
            tags={"emotes": tag}, username="a", channel="chan", raw=text,
        )

    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    msgs = []
    for i, (text, tag) in enumerate(
        [("Kappa", "25:0-4"), ("Keepo", "1902:0-4"), ("LUL", "425671:0-2"), ("OMEGALUL", "123:0-7")]
    ):
        msgs += [tagged(f"u{i}a", text, tag, base + timedelta(seconds=2 * i))]
        msgs += [tagged(f"u{i}b", text, tag, base + timedelta(seconds=2 * i + 1))]
    stats = cs.compute_stats(
        cs.messages_to_frame(msgs), make_params(include_emote_entropy=True), {}
    )
    assert stats["emote_entropy"] == 2.0

    dom = cs.messages_to_frame(
        [tagged(f"d{i}", "Kappa", "25:0-4", base + timedelta(seconds=i)) for i in range(8)]
    )
    stats_dom = cs.compute_stats(dom, make_params(include_emote_entropy=True), {})
    assert stats_dom["emote_entropy"] == 0.0


def test_lorenz_samples():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [("a", f"msg {i}", base + timedelta(minutes=i)) for i in range(10)]
    rows += [("b", "one", base), ("c", "one", base), ("d", "one", base), ("e", "one", base)]
    stats = cs.compute_stats(make_frame(rows), make_params(include_lorenz=True), {})
    assert stats["lorenz_samples"] == [
        {"top_pct": 1.0, "message_share_pct": round(10 / 14 * 100, 2)},
        {"top_pct": 5.0, "message_share_pct": round(10 / 14 * 100, 2)},
        {"top_pct": 10.0, "message_share_pct": round(10 / 14 * 100, 2)},
        {"top_pct": 25.0, "message_share_pct": round(11 / 14 * 100, 2)},
        {"top_pct": 50.0, "message_share_pct": round(12 / 14 * 100, 2)},
    ]


def test_bot_scores_flag_regular_spammer():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [("bot", "status ok", base + timedelta(seconds=10 * i)) for i in range(50)]
    rows += [
        ("human", "what a great stream today", base),
        ("human", "that play was insane", base + timedelta(minutes=37)),
        ("human", "ggs everyone", base + timedelta(hours=2)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(include_bot_scores=True), {})
    assert stats["bot_likelihood"] == [
        {
            "user_id": "bot",
            "username": "bot",
            "score": 0.8,
            "signals": ["regular_interval", "low_diversity"],
        }
    ]


def test_length_trend_slope():
    rows = [
        ("a", "a" * 10, datetime(2024, 1, 15, 10, 0, tzinfo=UTC)),
        ("a", "a" * 20, datetime(2024, 1, 16, 10, 0, tzinfo=UTC)),
        ("a", "a" * 30, datetime(2024, 1, 17, 10, 0, tzinfo=UTC)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(include_length_trend=True), {})
    assert stats["message_length_trend_slope"] == 10.0


def test_cohort_retention_week_alignment():
    # 2024-01-15 is a Monday. A active weeks 0 and 2, B only week 0.
    rows = [
        ("a", "first", datetime(2024, 1, 15, 10, 0, tzinfo=UTC)),
        ("a", "back", datetime(2024, 1, 29, 10, 0, tzinfo=UTC)),
        ("b", "once", datetime(2024, 1, 15, 11, 0, tzinfo=UTC)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(include_cohort_retention=True), {})
    assert stats["cohort_retention"] == [
        {
            "cohort_week": "2024-01-15",
            "cohort_size": 2,
            "retention": [
                {"week_offset": 0, "retention_pct": 100.0},
                {"week_offset": 2, "retention_pct": 50.0},
            ],
        }
    ]


def test_cohort_retention_caps_output():
    # 10 weekly Monday cohorts → only the most recent 8 are returned.
    rows = [
        (f"u{i}", "hello", datetime(2024, 1, 1, 10, 0, tzinfo=UTC) + timedelta(weeks=i))
        for i in range(10)
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(include_cohort_retention=True), {})
    cohorts = stats["cohort_retention"]
    assert len(cohorts) == 8
    assert cohorts[0]["cohort_week"] == "2024-01-15"
    assert all(c["retention"] == [{"week_offset": 0, "retention_pct": 100.0}] for c in cohorts)


def test_language_by_day_partitions_days(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("langdetect")
    fake_exc = types.ModuleType("langdetect.lang_detect_exception")

    class LangDetectException(Exception):
        pass

    class DetectorFactory:
        seed = 0

    def detect(text: str) -> str:
        if "boom" in text:
            raise ValueError("unclassifiable")
        return "fr" if "bonjour" in text else "en"

    fake.DetectorFactory = DetectorFactory
    fake.detect = detect
    fake_exc.LangDetectException = LangDetectException
    monkeypatch.setitem(sys.modules, "langdetect", fake)
    monkeypatch.setitem(sys.modules, "langdetect.lang_detect_exception", fake_exc)

    rows = [
        ("a", "bonjour monde ami camarade copain", datetime(2024, 1, 15, 10, 0, tzinfo=UTC)),
        ("b", "bonjour tout le monde les amis", datetime(2024, 1, 15, 11, 0, tzinfo=UTC)),
        ("c", "hello world friend fellow buddy", datetime(2024, 1, 16, 10, 0, tzinfo=UTC)),
        ("d", "boom", datetime(2024, 1, 16, 11, 0, tzinfo=UTC)),
    ]
    params = make_params(include_language=True, include_language_by_day=True)
    out = cs.compute_stats(make_frame(rows), params, {})["language_by_day"]
    assert [(entry["date"], entry["language"]) for entry in out] == [
        ("2024-01-15", "fr"),
        ("2024-01-16", "en"),
    ]


def test_language_by_day_reseed_is_stable(monkeypatch):
    """Day N's sample must not depend on how many messages earlier days had."""
    import sys
    import types

    fake = types.ModuleType("langdetect")
    fake_exc = types.ModuleType("langdetect.lang_detect_exception")

    class LangDetectException(Exception):
        pass

    class DetectorFactory:
        seed = 0

    def detect(text: str) -> str:
        return "fr" if "bonjour" in text else "en"

    fake.DetectorFactory = DetectorFactory
    fake.detect = detect
    fake_exc.LangDetectException = LangDetectException
    monkeypatch.setitem(sys.modules, "langdetect", fake)
    monkeypatch.setitem(sys.modules, "langdetect.lang_detect_exception", fake_exc)

    day2 = datetime(2024, 1, 16, 10, 0, tzinfo=UTC)
    late_rows = [("u", "hello world friend fellow buddy", day2 + timedelta(seconds=i)) for i in range(1000)]
    late_rows += [("u", "bonjour monde ami camarade copain", day2 + timedelta(seconds=2000 + i)) for i in range(5)]
    params = make_params(include_language=True, include_language_by_day=True)

    day1 = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    early_rows = [("u", "hello world friend fellow buddy", day1 + timedelta(seconds=i)) for i in range(1005)]

    with_both = cs.compute_stats(make_frame(early_rows + late_rows), params, {})["language_by_day"]
    late_only = cs.compute_stats(make_frame(late_rows), params, {})["language_by_day"]
    assert [e for e in with_both if e["date"] == "2024-01-16"] == late_only


def test_message_classes_single_pass_matches_expected():
    from app.scripts.chat_stats import _compute_message_classes, _parse_twitch_emotes

    df = pl.DataFrame({
        "text": ["hi", "Hello?", "LOUD NOISES", "!", "Kappa", "Kappa Kappa", "a" * 250, "x"],
        "emotes_tag": ["", "", "", "", "25:0-4", "25:0-4/25:6-10", "", ""],
    })
    twitch_emotes = _parse_twitch_emotes(df)
    result = _compute_message_classes(df, twitch_emotes, {})["message_classes"]
    assert result["questions"] == 1  # "Hello?"
    assert result["exclamations"] == 1  # "!"
    assert result["short_messages"] == 3  # "hi", "!", "x"
    assert result["long_messages"] == 1  # 250-char
    assert result["emote_only"] == 2  # "Kappa", "Kappa Kappa"


def test_poisson_upper_tail_known_value():
    # Poisson(10): P(X>=20) ≈ 0.0035, P(X>=21) ≈ 0.0016 (standard tables).
    p = cs._poisson_upper_tail(20, 10.0)
    assert abs(p - 0.0035) < 1e-4
    assert abs(cs._poisson_upper_tail(21, 10.0) - 0.0016) < 1e-4
    assert cs._poisson_upper_tail(0, 10.0) == 1.0
    assert cs._poisson_lower_tail(-1, 10.0) == 0.0
    # Degenerate lambda: all mass at 0.
    assert cs._poisson_upper_tail(1, 0.0) == 0.0
    assert cs._poisson_lower_tail(0, 0.0) == 1.0
    # Symmetric sanity: P(X<=10) + P(X>=11) == 1 for λ=10.
    lo = cs._poisson_lower_tail(10, 10.0)
    hi = cs._poisson_upper_tail(11, 10.0)
    assert abs(lo + hi - 1.0) < 1e-9


def test_weekly_seasonality_mean_is_one():
    base = datetime(2024, 1, 15, tzinfo=UTC)  # a Monday
    mpd = [
        {"date": (base + timedelta(days=i)).date().isoformat(), "count": 30 if (base + timedelta(days=i)).weekday() == 5 else 10}
        for i in range(14)
    ]
    trend, seasonality = cs._decompose_weekly_seasonality(mpd)
    assert seasonality is not None
    assert len(seasonality) == 7
    assert abs(sum(seasonality) / 7 - 1.0) < 1e-9
    assert seasonality[5] > 1.0  # Saturday runs hot
    assert len(trend) == 14
    assert cs._decompose_weekly_seasonality(mpd[:3]) == ([], None)


def test_quote_reply_window_boundary():
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = [
        ("bob", "im here", base),
        ("a", "@bob hi", base + timedelta(seconds=299)),
        ("a", "@bob late", base + timedelta(seconds=301)),
    ]
    stats = cs.compute_stats(make_frame(rows), make_params(include_quote_replies=True), {})
    assert stats["quote_reply_count"] == 1
    assert stats["quote_reply_pairs"] == [{"from_user": "a", "to_user": "bob", "count": 1}]


def test_zipf_slope_on_power_law():
    # Word i occurs ~(30/(i+1)) times: Zipf with slope ≈ -1 by construction.
    base = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    rows = []
    minute = 0
    for i in range(15):
        count = max(2, round(30 / (i + 1)))
        for _ in range(count):
            rows.append(("a", f"w{i:02d}", base + timedelta(minutes=minute)))
            minute += 1
    stats = cs.compute_stats(make_frame(rows), make_params(), {})
    assert stats["hapax_ratio"] == 0.0
    assert abs(stats["zipf_slope"] + 1.0) < 0.2
