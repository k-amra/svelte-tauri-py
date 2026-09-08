"""Tests for the on-disk parquet cache (tmp dir, no network)."""

import time
from datetime import UTC, datetime, timedelta

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


def test_fingerprint_is_channel_case_insensitive():
    assert log_cache.fingerprint("channel", "Demonzz1", None, None) == log_cache.fingerprint(
        "channel", "demonzz1", None, None
    )


def test_save_load_roundtrip():
    fp = log_cache.fingerprint("channel", "x", None, None)
    log_cache.save(fp, _frame(), {"fetched_at": time.time(), "immutable": True})
    hit = log_cache.load(fp)
    assert hit is not None
    df, meta = hit
    assert df.height == 2
    assert meta["immutable"] is True


def test_expired_live_entry_is_not_returned():
    fp = log_cache.fingerprint("channel", "x", None, None)
    log_cache.save(fp, _frame(), {"fetched_at": time.time() - 2 * log_cache.LIVE_TTL_S, "immutable": False})
    assert log_cache.load(fp) is None


def test_immutable_entry_never_expires():
    fp = log_cache.fingerprint("channel", "x", None, None)
    log_cache.save(fp, _frame(), {"fetched_at": 0.0, "immutable": True})
    assert log_cache.load(fp) is not None


def test_eviction_enforces_cap(monkeypatch):
    monkeypatch.setattr(log_cache, "MAX_CACHE_BYTES", 0)
    fp = log_cache.fingerprint("channel", "evictme", None, None)
    log_cache.save(fp, _frame(), {"fetched_at": time.time(), "immutable": True})
    assert log_cache.load(fp) is None


def test_live_entry_promotes_to_immutable_once_to_ages_past():
    fp = log_cache.fingerprint("channel", "promo", None, None)
    old_to = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    log_cache.save(
        fp,
        _frame(),
        {"fetched_at": time.time() - 2 * log_cache.LIVE_TTL_S, "immutable": False, "to": old_to},
    )
    hit = log_cache.load(fp)
    assert hit is not None
    assert hit[1]["immutable"] is True


def test_open_ended_entry_never_promotes():
    fp = log_cache.fingerprint("channel", "openended", None, None)
    log_cache.save(
        fp,
        _frame(),
        {"fetched_at": time.time() - 2 * log_cache.LIVE_TTL_S, "immutable": False, "to": None},
    )
    assert log_cache.load(fp) is None


def test_malformed_to_never_promotes():
    fp = log_cache.fingerprint("channel", "badto", None, None)
    log_cache.save(
        fp,
        _frame(),
        {"fetched_at": time.time() - 2 * log_cache.LIVE_TTL_S, "immutable": False, "to": "not-a-date"},
    )
    assert log_cache.load(fp) is None


def test_range_immutable_only_when_safely_in_the_past():
    past = datetime.now(UTC) - timedelta(days=1)
    assert log_cache.is_immutable_range(None, past) is True
    assert log_cache.is_immutable_range(None, None) is False
    assert log_cache.is_immutable_range(None, datetime.now(UTC)) is False
