"""Tests for the monthly-chunked parquet cache (tmp dir, no network)."""

import time
from datetime import UTC, datetime

import polars as pl
import pytest

from app.core import paths
from app.services import log_cache


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path):
    paths.init(str(tmp_path))


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "username": ["a", "b"],
            "text": ["hello", "world"],
            "ts": [datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC)],
        }
    )


def _meta(**overrides) -> dict:
    base = {
        "channel": "x",
        "channel_id_type": "channel",
        "year": 2024,
        "month": 1,
        "fetched_at": time.time(),
        "immutable": True,
        "truncated": False,
        "covered_from": "2024-01-01T00:00:00+00:00",
        "covered_to": "2024-02-01T00:00:00+00:00",
        "complete": True,
        "message_count": 2,
        "twitch_id": None,
    }
    base.update(overrides)
    return base


def test_month_bounds_roll_over_december():
    start, end = log_cache.month_bounds(2024, 12)
    assert (start.year, start.month, start.day) == (2024, 12, 1)
    assert (end.year, end.month, end.day) == (2025, 1, 1)
    assert log_cache.month_key(2024, 1) == "2024_01"


def test_channel_dir_is_case_insensitive():
    assert log_cache.get_month_paths("channel", "Demonzz1", 2024, 1) == log_cache.get_month_paths(
        "channel", "demonzz1", 2024, 1
    )


def test_save_load_roundtrip():
    log_cache.save_month("channel", "x", 2024, 1, _frame(), _meta())
    hit = log_cache.load_month("channel", "x", 2024, 1)
    assert hit is not None
    df, meta = hit
    assert df.height == 2
    assert meta["immutable"] is True
    assert meta["covered_from"] == "2024-01-01T00:00:00+00:00"


def test_missing_month_returns_none():
    assert log_cache.load_month("channel", "x", 2024, 3) is None


def test_old_flag_promotes_once_month_ages_past():
    log_cache.save_month(
        "channel",
        "x",
        2024,
        1,
        _frame(),
        _meta(immutable=False, fetched_at=time.time() - 2 * log_cache.LIVE_TTL_S),
    )
    # January 2024 is long past: promotes to immutable despite the old flag.
    hit = log_cache.load_month("channel", "x", 2024, 1)
    assert hit is not None
    assert hit[1]["immutable"] is True


def test_expired_current_month_is_not_returned_without_stale():
    now = datetime.now(UTC)
    log_cache.save_month(
        "channel",
        "x",
        now.year,
        now.month,
        _frame(),
        _meta(immutable=False, fetched_at=time.time() - 2 * log_cache.LIVE_TTL_S),
    )
    assert log_cache.load_month("channel", "x", now.year, now.month) is None
    stale = log_cache.load_month("channel", "x", now.year, now.month, allow_stale=True)
    assert stale is not None


def test_immutable_month_never_expires():
    log_cache.save_month("channel", "x", 2024, 1, _frame(), _meta(fetched_at=0.0))
    assert log_cache.load_month("channel", "x", 2024, 1) is not None


def test_is_month_immutable():
    assert log_cache.is_month_immutable(2020, 5) is True
    now = datetime.now(UTC)
    assert log_cache.is_month_immutable(now.year, now.month) is False


def test_eviction_enforces_cap_across_channels(monkeypatch):
    monkeypatch.setattr(log_cache, "MAX_CACHE_BYTES", 0)
    monkeypatch.setattr(log_cache, "_last_evict_ts", 0.0)
    log_cache.save_month("channel", "evictme", 2024, 1, _frame(), _meta())
    assert log_cache.load_month("channel", "evictme", 2024, 1) is None


def test_eviction_throttled_within_interval(monkeypatch):
    calls: list = []
    monkeypatch.setattr(log_cache, "_last_evict_ts", 0.0)
    monkeypatch.setattr(log_cache, "_evict_if_needed", lambda: calls.append(1))
    log_cache.save_month("channel", "a", 2024, 1, _frame(), _meta())
    log_cache.save_month("channel", "b", 2024, 1, _frame(), _meta())
    assert len(calls) == 1  # second save skips the sweep
    monkeypatch.setattr(log_cache, "_last_evict_ts", 0.0)
    log_cache.save_month("channel", "c", 2024, 1, _frame(), _meta())
    assert len(calls) == 2
