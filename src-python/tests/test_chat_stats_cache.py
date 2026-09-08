"""Tests for the chat_stats cache integration (fetch stubbed, disk real)."""

from datetime import UTC, datetime

import pytest

from app.core import paths
from app.scripts import chat_stats
from app.services.harambelogs_models import FullMessage


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path):
    paths.init(str(tmp_path))


def _msg(i: int) -> FullMessage:
    return FullMessage(
        type=0,
        text=f"message {i}",
        displayName="User",
        timestamp=datetime(2024, 1, 1, 12, i % 60, tzinfo=UTC),
        id=str(i),
        tags={},
        username="user",
        channel="chan",
        raw=f":user!u@h PRIVMSG #chan :message {i}",
    )


def test_second_run_hits_cache_and_force_bypasses(monkeypatch):
    calls = {"n": 0}

    async def fake_fetch(params, progress):
        calls["n"] += 1
        return [_msg(i) for i in range(5)], False

    monkeypatch.setattr(chat_stats, "_fetch_all", fake_fetch)

    params = chat_stats.Params(
        channel="chan", from_date=datetime(2024, 1, 1, tzinfo=UTC), to_date=datetime(2024, 1, 2, tzinfo=UTC)
    )
    r1 = chat_stats.run(params)
    assert r1.from_cache is False

    r2 = chat_stats.run(params)
    assert r2.from_cache is True
    assert r2.cached_at is not None
    assert calls["n"] == 1
    assert r2.total_messages == r1.total_messages

    chat_stats.run(chat_stats.Params(**{**params.model_dump(), "force_refresh": True}))
    assert calls["n"] == 2
