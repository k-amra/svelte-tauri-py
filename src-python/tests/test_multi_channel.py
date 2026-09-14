"""Tests for multi-channel fetching and per-channel summaries."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import polars as pl

from app.scripts import chat_stats
from app.scripts.chat_stats import fetcher
from app.scripts.chat_stats.analytics.per_channel import compute_channel_summary
from app.scripts.chat_stats.frame import messages_to_frame
from app.services.harambelogs_models import FullMessage

BASE = datetime(2025, 1, 10, tzinfo=UTC)


def _msg(user_id: str, channel: str, minutes: int) -> FullMessage:
    return FullMessage(
        type=0,
        text="hello",
        displayName=f"u{user_id}",
        timestamp=BASE + timedelta(minutes=minutes),
        id=f"{channel}-{user_id}-{minutes}",
        tags={"room-id": "12345", "user-id": user_id},
        username=f"u{user_id}",
        channel=channel,
        raw="hello",
    )


def _params(**overrides) -> chat_stats.Params:
    defaults = dict(
        channel="a",
        channels=["a", "b"],
        from_date=BASE,
        to_date=BASE + timedelta(days=1),
    )
    defaults.update(overrides)
    return chat_stats.Params(**defaults)


def test_run_all_merges_channels_and_tags_rows(monkeypatch) -> None:
    seen_channels: list[str] = []

    async def fake_run_chunked(params, progress, api=None, channel=None, channel_id_type=None):
        assert channel is not None
        seen_channels.append(channel)
        n = 2 if channel == "a" else 1
        return messages_to_frame([_msg(str(i), channel, i) for i in range(n)]), False, False, "1", None, False

    async def fake_emotes(channel: str, twitch_id: str | None):
        return {channel: "Emote"}

    monkeypatch.setattr(fetcher, "_run_chunked", fake_run_chunked)
    monkeypatch.setattr(fetcher, "_safe_fetch_emotes", fake_emotes)

    df, any_fetch, truncated, twitch_id, cached_at, emote_maps, emote_map, _outside = (
        asyncio.run(chat_stats.run_all(_params(), lambda p, m: None))
    )

    assert seen_channels == ["a", "b"]
    assert "channel" in df.columns
    assert df.height == 3
    assert sorted(df["channel"].unique().to_list()) == ["a", "b"]
    # Emote maps are unioned.
    assert emote_map == {"a": "Emote", "b": "Emote"}
    assert emote_maps == [{"a": "Emote"}, {"b": "Emote"}]
    # Multi-channel runs have no single twitch_id.
    assert twitch_id is None
    assert any_fetch is False


def test_run_all_single_channel_fast_path_untagged(monkeypatch) -> None:
    async def fake_run_chunked(params, progress, api=None, channel=None, channel_id_type=None):
        return messages_to_frame([_msg("1", "a", 0)]), False, False, "42", None, False

    monkeypatch.setattr(fetcher, "_run_chunked", fake_run_chunked)

    df, _af, _t, twitch_id, _c, _em, _e, _o = asyncio.run(
        chat_stats.run_all(_params(channels=["a"], channel="a"), lambda p, m: None)
    )
    assert "channel" not in df.columns
    assert twitch_id == "42"


def test_multi_channel_run_attaches_summaries_and_warnings(monkeypatch) -> None:
    async def fake_run_all(params, progress, api=None):
        frames = []
        for i, ch in enumerate(params.channels):
            frames.append(
                messages_to_frame([_msg(str(j), ch, j) for j in range(3 - i)])
                .with_columns(pl.lit(ch).alias("channel"))
            )
        df = pl.concat(frames, how="vertical").sort("ts")
        return df, False, False, None, None, [{}, {}], {}, []

    monkeypatch.setattr(chat_stats, "run_all", fake_run_all)
    result = chat_stats.run(_params())

    assert result.channel_summaries is not None
    assert [s.channel for s in result.channel_summaries] == ["a", "b"]
    assert [s.total_messages for s in result.channel_summaries] == [3, 2]
    # Sums reconcile: no dedupe warning.
    assert not any("sum to" in w for w in result.warnings)


def test_pooled_top_chatters_carry_channel_attribution(monkeypatch) -> None:
    """Pooled runs record which channel(s) each top chatter appeared in."""

    async def fake_run_all(params, progress, api=None):
        frames = [
            messages_to_frame(
                [_msg("1", "a", 0), _msg("1", "a", 1), _msg("2", "a", 2)]
            ).with_columns(pl.lit("a").alias("channel")),
            messages_to_frame([_msg("1", "b", 3)]).with_columns(pl.lit("b").alias("channel")),
        ]
        df = pl.concat(frames, how="vertical").sort("ts")
        return df, False, False, None, None, [{}, {}], {}, []

    monkeypatch.setattr(chat_stats, "run_all", fake_run_all)
    result = chat_stats.run(_params())

    by_user = {t.user_id: t for t in result.top_chatters}
    assert by_user["1"].channels == ["a", "b"]
    assert by_user["2"].channels == ["a"]


def test_single_channel_top_chatters_leave_channels_empty(monkeypatch) -> None:
    async def fake_run_all(params, progress, api=None):
        return messages_to_frame([_msg("1", "a", 0)]), False, False, None, None, [{}], {}, []

    monkeypatch.setattr(chat_stats, "run_all", fake_run_all)
    result = chat_stats.run(_params(channels=["a"], channel="a"))

    assert [t.channels for t in result.top_chatters] == [[]]


def test_multi_channel_run_warns_on_zero_message_channel(monkeypatch) -> None:
    async def fake_run_all(params, progress, api=None):
        frames = [
            messages_to_frame([_msg("1", "a", 0)]).with_columns(pl.lit("a").alias("channel")),
            messages_to_frame([]).with_columns(pl.lit("b").alias("channel")),
        ]
        df = pl.concat(frames, how="vertical").sort("ts")
        return df, False, False, None, None, [{}, {}], {}, []

    monkeypatch.setattr(chat_stats, "run_all", fake_run_all)
    result = chat_stats.run(_params())

    assert result.channel_summaries[1].total_messages == 0
    assert any("returned no messages" in w for w in result.warnings)


def test_channel_summary_aligns_days_to_merged_span() -> None:
    # Channel b is quiet on the first day of the merged span.
    df = pl.concat(
        [
            messages_to_frame([_msg("1", "a", 0)]).with_columns(pl.lit("a").alias("channel")),
            messages_to_frame([_msg("2", "b", 24 * 60)]).with_columns(pl.lit("b").alias("channel")),
        ]
    ).sort("ts")
    summary = compute_channel_summary(
        df,
        "b",
        {},
        stopwords=frozenset(),
        merged_min_date=BASE.date(),
        merged_max_date=BASE.date() + timedelta(days=2),
    )
    assert summary.total_messages == 1
    assert [d.count for d in summary.messages_per_day] == [0, 1, 0]
    assert summary.first_message is not None
    # A quiet channel still gets the full aligned zero array.
    empty = compute_channel_summary(
        df,
        "ghost",
        {},
        stopwords=frozenset(),
        merged_min_date=BASE.date(),
        merged_max_date=BASE.date() + timedelta(days=1),
    )
    assert empty.total_messages == 0
    assert [d.count for d in empty.messages_per_day] == [0, 0]


def _msg_text(user_id: str, channel: str, minutes: int, text: str) -> FullMessage:
    return FullMessage(
        type=0,
        text=text,
        displayName=f"u{user_id}",
        timestamp=BASE + timedelta(minutes=minutes),
        id=f"{channel}-{user_id}-{minutes}-{text}",
        tags={"room-id": "12345", "user-id": user_id},
        username=f"u{user_id}",
        channel=channel,
        raw=text,
    )


def test_multi_channel_run_computes_full_per_channel_stats(monkeypatch) -> None:
    """Pooled runs return isolated full stats per channel (not just summaries)."""

    async def fake_run_all(params, progress, api=None):
        frames = [
            messages_to_frame(
                [
                    _msg_text("1", "a", 0, "alpha alpha alpha"),
                    _msg_text("1", "a", 1, "alpha beta"),
                    _msg_text("2", "a", 2, "alpha gamma"),
                ]
            ).with_columns(pl.lit("a").alias("channel")),
            messages_to_frame(
                [
                    _msg_text("3", "b", 3, "delta delta delta"),
                    _msg_text("4", "b", 4, "delta epsilon"),
                ]
            ).with_columns(pl.lit("b").alias("channel")),
        ]
        df = pl.concat(frames, how="vertical").sort("ts")
        return df, False, False, None, None, [{}, {}], {}, []

    monkeypatch.setattr(chat_stats, "run_all", fake_run_all)
    result = chat_stats.run(_params())

    assert [c.channel for c in result.per_channel] == ["a", "b"]
    by_channel = {c.channel: c for c in result.per_channel}
    assert by_channel["a"].total_messages == 3
    assert by_channel["b"].total_messages == 2
    # Full shapes are populated, not just headline counts.
    assert by_channel["a"].unique_chatters == 2
    assert by_channel["b"].unique_chatters == 2
    assert sum(by_channel["a"].activity_by_hour) == 3
    assert sum(by_channel["b"].activity_by_hour) == 2
    # Isolation: each channel's vocabulary stays its own.
    words_a = {w.word for w in by_channel["a"].top_words}
    words_b = {w.word for w in by_channel["b"].top_words}
    assert "alpha" in words_a
    assert "delta" in words_b
    assert "delta" not in words_a
    assert "alpha" not in words_b
    # Per-channel entries are single-channel shaped (no nesting).
    assert by_channel["a"].channel_summaries == []
    assert by_channel["a"].per_channel == []
    assert by_channel["a"].previous_period is None


def test_multi_channel_per_channel_empty_channel_is_zeroed(monkeypatch) -> None:
    async def fake_run_all(params, progress, api=None):
        frames = [
            messages_to_frame([_msg("1", "a", 0)]).with_columns(pl.lit("a").alias("channel")),
            messages_to_frame([]).with_columns(pl.lit("b").alias("channel")),
        ]
        df = pl.concat(frames, how="vertical").sort("ts")
        return df, False, False, None, None, [{}, {}], {}, []

    monkeypatch.setattr(chat_stats, "run_all", fake_run_all)
    result = chat_stats.run(_params())

    by_channel = {c.channel: c for c in result.per_channel}
    assert by_channel["b"].total_messages == 0
    assert by_channel["b"].top_chatters == []
    assert by_channel["b"].activity_by_hour == [0] * 24


def test_single_channel_run_has_no_per_channel(monkeypatch) -> None:
    async def fake_run_all(params, progress, api=None):
        return messages_to_frame([_msg("1", "a", 0)]), False, False, None, None, [{}], {}, []

    monkeypatch.setattr(chat_stats, "run_all", fake_run_all)
    result = chat_stats.run(_params(channels=["a"], channel="a"))

    assert result.per_channel == []
