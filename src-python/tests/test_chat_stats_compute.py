"""Unit tests for the pure analytics layer (no network)."""

from datetime import UTC, datetime

import polars as pl

from app.scripts import chat_stats as cs
from app.services.harambelogs_models import FullMessage

UTC = UTC
TS = pl.Datetime(time_unit="us", time_zone="UTC")


def make_frame(rows: list[tuple[str, str, datetime]]) -> pl.DataFrame:
    usernames, texts, stamps = zip(*rows, strict=True)
    return pl.DataFrame(
        {
            "username": list(usernames),
            "text": list(texts),
            "ts": pl.Series(list(stamps), dtype=TS),
        }
    )


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
    )
    stats = cs.compute_stats(make_frame(rows), top_n=2)
    assert stats["total_messages"] == 30
    assert stats["unique_chatters"] == 3
    assert stats["days_spanned"] == 2
    assert [t["username"] for t in stats["top_chatters"]] == ["a", "b"]
    assert stats["top_chatters"][0]["messageCount"] == 15
    assert stats["activity_by_hour"][10] == 15
    assert stats["activity_by_hour"][11] == 10
    assert stats["activity_by_hour"][12] == 5
    assert stats["messages_per_day"] == [
        {"date": "2024-01-15", "count": 25},
        {"date": "2024-01-16", "count": 5},
    ]


def test_heatmap_shape_and_monday_placement():
    # 2024-01-15 is a Monday; 2024-01-21 is a Sunday.
    rows = [
        ("a", "hello", datetime(2024, 1, 15, 10, 30, tzinfo=UTC)),
        ("b", "world hello", datetime(2024, 1, 21, 23, 0, tzinfo=UTC)),
    ]
    stats = cs.compute_stats(make_frame(rows), top_n=20)
    heat = stats["activity_by_weekday_hour"]
    assert len(heat) == 7 and all(len(row) == 24 for row in heat)
    assert heat[0][10] == 1  # Monday 10:00 UTC
    assert heat[6][23] == 1  # Sunday 23:00 UTC
    assert sum(sum(row) for row in heat) == 2


def test_top_words_filters_stopwords_and_short_tokens():
    rows = [
        ("a", "Hello hello the a x PogChamp", datetime(2024, 1, 15, 10, 0, tzinfo=UTC)),
    ]
    stats = cs.compute_stats(make_frame(rows), top_n=20)
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
    stats = cs.compute_stats(make_frame(rows), 20, {"25": "Kappa", "b1": "KEKW"})
    words = {w["word"]: w["count"] for w in stats["top_words"]}
    assert "kappa" not in words
    assert "kekw" not in words
    assert words.get("hello") == 2
    assert words.get("world") == 1


def test_extra_stopwords_exclude_native_emote_names():
    rows = [("a", "Kappa hello", datetime(2024, 1, 15, 10, 0, tzinfo=UTC))]
    stats = cs.compute_stats(make_frame(rows), 20, {}, frozenset({"kappa"}))
    words = {w["word"] for w in stats["top_words"]}
    assert "kappa" not in words
    assert "hello" in words


def test_empty_frame_returns_zeroed_shapes():
    stats = cs.compute_stats(cs.messages_to_frame([]), top_n=20)
    assert stats["total_messages"] == 0
    assert stats["unique_chatters"] == 0
    assert stats["days_spanned"] == 0
    assert stats["avg_message_length"] == 0.0
    assert stats["top_chatters"] == []
    assert stats["activity_by_hour"] == [0] * 24
    assert stats["activity_by_weekday_hour"] == [[0] * 24 for _ in range(7)]
    assert stats["messages_per_day"] == []
    assert stats["top_words"] == []


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
