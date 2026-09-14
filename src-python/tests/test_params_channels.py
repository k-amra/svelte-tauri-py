"""Tests for multi-channel params normalization and the channels validator."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.scripts.chat_stats import Params

BASE = datetime(2025, 1, 1, tzinfo=UTC)


def _params(**overrides) -> Params:
    defaults = dict(
        channel="c",
        from_date=BASE,
        to_date=datetime(2025, 1, 2, tzinfo=UTC),
    )
    defaults.update(overrides)
    return Params(**defaults)


def test_single_channel_coerced_to_channels() -> None:
    p = _params()
    assert p.channels == ["c"]
    assert p.channel == "c"


def test_explicit_channels_win_over_channel() -> None:
    p = _params(channel="legacy", channels=["a", "b"])
    assert p.channels == ["a", "b"]
    # Multi-channel runs have no single legacy channel.
    assert p.channel is None


def test_channels_deduped_case_insensitively() -> None:
    p = _params(channels=["Alice", " alice ", "ALICE", "bob"])
    assert p.channels == ["Alice", "bob"]
    # First-seen casing wins.
    assert p.channel is None


def test_channels_capped_at_three() -> None:
    with pytest.raises(ValueError, match="at most 3 channels"):
        _params(channels=["a", "b", "c", "d"])


def test_no_channels_rejected() -> None:
    with pytest.raises(ValueError, match="at least one channel"):
        _params(channel=None)
    with pytest.raises(ValueError, match="at least one non-empty"):
        _params(channels=["   ", ""])


def test_multi_channel_keeps_single_channel_fields_valid() -> None:
    p = _params(channels=["x", "y"])
    # Other validators still run on multi-channel params.
    assert p.top_n == 20
    assert p.from_date < p.to_date
