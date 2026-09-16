"""Direct tests for orchestrator._sanity_warnings (surfaced as a UI banner)."""

from datetime import datetime

import polars as pl

from app.scripts.chat_stats.orchestrator import _sanity_warnings


def _df(texts: list[str], start_hour: int = 10) -> pl.DataFrame:
    # Naive datetimes are deliberate: the only ts-consuming check
    # (monotonicity via diff) is tz-agnostic.
    ts = [datetime(2024, 1, 15, start_hour, i) for i in range(len(texts))]
    return pl.DataFrame({"text": texts, "ts": ts})


def _stats(**overrides) -> dict:
    base: dict = {
        "avg_message_length": 11.0,
        "messages_per_day": [{"date": "2024-01-15", "count": 3}],
        "days_spanned": 1,
        "activity_by_hour": [0] * 10 + [3] + [0] * 13,
        "total_messages": 3,
    }
    base.update(overrides)
    return base


def test_implausibly_small_avg_message_length():
    df = _df(["hi", "yo", "ok"])
    warnings = _sanity_warnings(df, _stats(avg_message_length=2.0))
    assert any("implausibly small" in w for w in warnings)


def test_implausibly_large_avg_message_length():
    df = _df(["hi", "yo", "ok"])
    warnings = _sanity_warnings(df, _stats(avg_message_length=500.0))
    assert any("implausibly large" in w for w in warnings)


def test_day_count_mismatch():
    df = _df(["hello world", "foo bar baz", "lorem ipsum dolor"])
    warnings = _sanity_warnings(df, _stats(days_spanned=2))
    assert any("days_spanned=2" in w for w in warnings)


def test_hourly_sum_mismatch():
    df = _df(["hello world", "foo bar baz", "lorem ipsum dolor"])
    warnings = _sanity_warnings(df, _stats(activity_by_hour=[0] * 24))
    assert any("total_messages=3" in w for w in warnings)


def test_empty_text_flagged():
    df = _df(["hello world", "", "foo bar baz"])
    warnings = _sanity_warnings(df, _stats())
    assert any("empty text" in w for w in warnings)


def test_non_monotonic_timestamps_flagged():
    df = _df(["hello world", "foo bar baz", "lorem ipsum dolor"])
    df = df.sort("ts", descending=True)
    warnings = _sanity_warnings(df, _stats())
    assert any("not monotonic" in w for w in warnings)


def test_clean_data_has_no_warnings():
    df = _df(["hello world", "foo bar baz", "lorem ipsum dolor"])
    assert _sanity_warnings(df, _stats()) == []
