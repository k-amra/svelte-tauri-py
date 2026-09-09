"""Tests for incremental cache refresh (stale entry + delta download)."""

import time
from datetime import UTC, datetime, timedelta

import pytest

from app.core import paths
from app.scripts import chat_stats
from app.services import log_cache
from app.services.harambelogs_models import FullMessage

BASE = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def _live_range() -> tuple[datetime, datetime]:
    """Explicit range whose `to` is recent: expired entries over it stay
    stale (never promote to immutable), exercising the top-up path."""
    to_date = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=30)
    return to_date - timedelta(days=1), to_date


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path):
    paths.init(str(tmp_path))


def _msg(mid: str, ts: datetime, text: str = "hello world") -> FullMessage:
    return FullMessage(
        type=0,
        text=text,
        displayName="u",
        timestamp=ts,
        id=mid,
        tags={},
        username="u",
        channel="chan",
        raw=text,
    )


def _seed(fp: str, messages: list[FullMessage], fetched_ago_s: float, **meta_extra) -> float:
    fetched_at = time.time() - fetched_ago_s
    meta = {
        "channel": "chan",
        "channel_id_type": "channel",
        "from": None,
        "to": None,
        "fetched_at": fetched_at,
        "immutable": False,
        "truncated": False,
        "message_count": len(messages),
        "twitch_id": None,
        **meta_extra,
    }
    log_cache.save(fp, chat_stats.messages_to_frame(messages), meta)
    return fetched_at


def _params(from_date: datetime, to_date: datetime, **overrides):
    base = {"channel": "chan", "from_date": from_date, "to_date": to_date}
    base.update(overrides)
    return chat_stats.Params(**base)


def _fp(from_date: datetime | None, to_date: datetime | None) -> str:
    return log_cache.fingerprint("channel", "chan", from_date, to_date)


def _stub_network(monkeypatch, fetched: list[FullMessage], seen: list):
    async def fake_fetch(p, progress):
        seen.append(p)
        return fetched, False

    async def fake_emotes(channel_name, user_id):
        return {}

    monkeypatch.setattr(chat_stats, "_fetch_all", fake_fetch)
    monkeypatch.setattr(chat_stats, "fetch_channel_emotes", fake_emotes)


def test_top_up_appends_delta_and_dedupes_overlap(monkeypatch):
    from_date, to_date = _live_range()
    fp = _fp(from_date, to_date)
    t0, t1, t2 = (
        BASE,
        BASE.replace(hour=13),
        BASE.replace(hour=14),
    )
    # Seed the fetch strictly before `to` so the coverage shortcut below
    # does not trigger: this test must exercise the delta download.
    fetched_at = _seed(
        fp,
        [_msg("m1", t0), _msg("m2", t1)],
        2 * log_cache.LIVE_TTL_S + 120,
        **{"from": from_date.isoformat(), "to": to_date.isoformat()},
    )
    seen: list = []
    # m2 overlaps the cached window (same id) and must not double-count.
    _stub_network(monkeypatch, [_msg("m2", t1), _msg("m3", t2)], seen)

    result = chat_stats.run(_params(from_date, to_date))

    assert len(seen) == 1
    assert seen[0].from_date == datetime.fromtimestamp(fetched_at, UTC)
    assert result.total_messages == 3
    assert result.from_cache is False
    assert result.truncated is False
    # Second run is a fresh hit now (TTL refreshed by the top-up save).
    assert chat_stats.run(_params(from_date, to_date)).from_cache is True


def test_top_up_skips_fetch_when_range_already_covered(monkeypatch):
    # Expired (fetched 20 min ago) but `to` predates the fetch and is still
    # inside the immutability margin: stale, yet fully covered — no download.
    to_date = datetime.fromtimestamp(time.time() - 1800, UTC)
    from_date = to_date - timedelta(days=1)
    fp = _fp(from_date, to_date)
    _seed(
        fp,
        [_msg("m1", BASE)],
        1200,
        **{"from": from_date.isoformat(), "to": to_date.isoformat(), "immutable": False},
    )

    async def _no_fetch(p, progress):
        raise AssertionError("no download expected")

    async def fake_emotes(channel_name, user_id):
        return {}

    monkeypatch.setattr(chat_stats, "_fetch_all", _no_fetch)
    monkeypatch.setattr(chat_stats, "fetch_channel_emotes", fake_emotes)

    result = chat_stats.run(_params(from_date, to_date))
    assert result.from_cache is True
    assert result.total_messages == 1


def test_top_up_preserves_truncated_flag(monkeypatch):
    from_date, to_date = _live_range()
    fp = _fp(from_date, to_date)
    _seed(
        fp,
        [_msg("m1", BASE)],
        2 * log_cache.LIVE_TTL_S + 120,
        **{"from": from_date.isoformat(), "to": to_date.isoformat(), "truncated": True},
    )
    seen: list = []
    _stub_network(monkeypatch, [_msg("m2", BASE.replace(hour=13))], seen)
    result = chat_stats.run(_params(from_date, to_date))
    assert result.truncated is True
    assert result.total_messages == 2


def test_frame_carries_message_ids():
    df = chat_stats.messages_to_frame([_msg("abc", BASE)])
    assert df["id"].to_list() == ["abc"]
