"""Behavior tests for the optional single-user filter in chat_stats."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from app.scripts.chat_stats import Params, compute_stats


def _frame() -> pl.DataFrame:
    base = datetime(2025, 1, 1, tzinfo=UTC)
    rows = [
        ("u1", "alice", "hello world", base, "", "m1", "regular"),
        ("u1", "alice", "hello again", base + timedelta(minutes=1), "", "m2", "regular"),
        ("u2", "bob", "LUL hello", base + timedelta(minutes=2), "", "m3", "moderator"),
        ("u2", "bob", "hello world", base + timedelta(minutes=3), "", "m4", "moderator"),
        ("u3", "carol", "!command", base + timedelta(minutes=4), "", "m5", "regular"),
    ]
    return pl.DataFrame(
        {
            "user_id": pl.Series([r[0] for r in rows], dtype=pl.String),
            "username": pl.Series([r[1] for r in rows], dtype=pl.String),
            "text": pl.Series([r[2] for r in rows], dtype=pl.String),
            "ts": pl.Series([r[3] for r in rows], dtype=pl.Datetime("us", "UTC")),
            "emotes_tag": pl.Series([r[4] for r in rows], dtype=pl.String),
            "id": pl.Series([r[5] for r in rows], dtype=pl.String),
            "role": pl.Series([r[6] for r in rows], dtype=pl.String),
        }
    ).sort("ts")


def _params(**overrides) -> Params:
    defaults = dict(
        channel="c",
        from_date=datetime(2025, 1, 1, tzinfo=UTC),
        to_date=datetime(2025, 1, 2, tzinfo=UTC),
    )
    defaults.update(overrides)
    return Params(**defaults)


def test_no_user_filter_is_unchanged() -> None:
    """`user=None` must not alter the whole-channel result."""
    out = compute_stats(_frame(), _params(), {})
    assert out["total_messages"] == 5
    assert out["unique_chatters"] == 3
    assert len(out["top_chatters"]) == 3


def test_user_filter_by_login() -> None:
    out = compute_stats(_frame(), _params(user="bob"), {})
    assert out["total_messages"] == 2
    assert out["unique_chatters"] == 1
    assert out["top_chatters"][0]["username"] == "bob"
    assert out["top_chatters"][0]["messageCount"] == 2


def test_user_filter_is_case_insensitive() -> None:
    out = compute_stats(_frame(), _params(user="BOB"), {})
    assert out["total_messages"] == 2


def test_user_filter_by_userid() -> None:
    out = compute_stats(
        _frame(), _params(user="u2", user_id_type="userid"), {}
    )
    assert out["total_messages"] == 2
    assert out["top_chatters"][0]["user_id"] == "u2"


def test_user_filter_that_matches_nothing_returns_empty_shape() -> None:
    out = compute_stats(_frame(), _params(user="nobody"), {})
    assert out["total_messages"] == 0
    assert out["unique_chatters"] == 0
    assert out["top_chatters"] == []
    assert out["top_emotes"] == []


def test_params_rejects_empty_user() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        _params(user="   ")


def test_params_accepts_omitted_user() -> None:
    p = _params()
    assert p.user is None
    assert p.user_id_type == "user"
