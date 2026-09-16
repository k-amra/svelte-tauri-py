"""Tests for monthly-chunk tail refresh (stale live month + delta download)."""

import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core import paths
from app.scripts import chat_stats
from app.scripts.chat_stats import fetcher
from app.services import log_cache
from app.services.harambelogs_client import HarambelogsAPI, HarambelogsError
from app.services.harambelogs_models import FullMessage


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path):
    paths.init(str(tmp_path))


@pytest.fixture(autouse=True)
def _no_calendar(monkeypatch):
    """Keep these tests offline: no /list probe unless a test opts in."""

    async def _none(api, channel_id_type, channel):
        return None

    monkeypatch.setattr(fetcher, "channel_log_days", _none)


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


def _september_msgs() -> list[FullMessage]:
    return [_msg(f"m{d}", datetime(2024, 9, d, 12, 0, tzinfo=UTC)) for d in range(1, 11)]


def _seed_month(
    year: int,
    month: int,
    messages: list[FullMessage],
    fetched_ago_s: float,
    **meta_extra,
) -> float:
    fetched_at = time.time() - fetched_ago_s
    df = chat_stats.messages_to_frame(messages)
    stamps = [m.timestamp for m in messages]
    meta = {
        "channel": "chan",
        "channel_id_type": "channel",
        "year": year,
        "month": month,
        "fetched_at": fetched_at,
        "immutable": False,
        "truncated": False,
        "covered_from": (min(stamps).isoformat() if stamps else None),
        "covered_to": (max(stamps).isoformat() if stamps else None),
        "complete": False,
        "message_count": len(messages),
        "twitch_id": None,
        **meta_extra,
    }
    log_cache.save_month("channel", "chan", year, month, df, meta)
    return fetched_at


def _params(from_date: datetime, to_date: datetime, **overrides):
    base = {"channel": "chan", "from_date": from_date, "to_date": to_date}
    base.update(overrides)
    return chat_stats.Params(**base)


def _stub_fetch(monkeypatch, pool: list[FullMessage], calls: list, truncated: bool = False):
    async def fake_fetch(api, channel_id_type, channel, from_date, to_date, **kwargs):
        calls.append((from_date, to_date))
        return [m for m in pool if from_date <= m.timestamp <= to_date], truncated

    async def fake_emotes(channel_name, user_id):
        return {}

    monkeypatch.setattr(fetcher, "fetch_channel_logs", fake_fetch)
    monkeypatch.setattr(fetcher, "fetch_channel_emotes", fake_emotes)


def _near_month_boundary() -> bool:
    """True when a live-month range cannot be built (month's first minutes)."""
    now = datetime.now(UTC).replace(microsecond=0)
    to_date = now - timedelta(minutes=30)
    month_start = datetime(to_date.year, to_date.month, 1, tzinfo=UTC)
    from_date = max(month_start, to_date - timedelta(days=2))
    return from_date >= to_date or to_date.month != now.month or to_date.year != now.year


def _live_month_range() -> tuple[datetime, datetime]:
    """Range inside the current (live) month; skips on the month's first minutes."""
    if _near_month_boundary():
        pytest.skip("too close to a month boundary for a live-month scenario")
    now = datetime.now(UTC).replace(microsecond=0)
    to_date = now - timedelta(minutes=30)
    month_start = datetime(to_date.year, to_date.month, 1, tzinfo=UTC)
    return max(month_start, to_date - timedelta(days=2)), to_date


requires_live_month = pytest.mark.skipif(
    _near_month_boundary(),
    reason="too close to a month boundary for a live-month scenario",
)


@requires_live_month
def test_stale_live_month_refreshes_only_the_tail(monkeypatch):
    from_date, to_date = _live_month_range()
    seed_ts = from_date + (to_date - from_date) / 2
    fetched_at = _seed_month(
        from_date.year, from_date.month, [_msg("m1", seed_ts)], 2 * log_cache.LIVE_TTL_S + 120
    )
    # Overwrite coverage to the full requested span with an old fetch time.
    df, meta = log_cache.load_month("channel", "chan", from_date.year, from_date.month, allow_stale=True)
    assert df is not None
    meta.update({"covered_from": from_date.isoformat(), "covered_to": to_date.isoformat()})
    log_cache.save_month("channel", "chan", from_date.year, from_date.month, df, meta)

    tail_msg_ts = to_date - timedelta(minutes=5)
    calls: list = []
    _stub_fetch(monkeypatch, [_msg("m2", tail_msg_ts)], calls)

    result = chat_stats.run(_params(from_date, to_date))

    # One delta fetch starting at last-fetch minus the overlap, not a redownload.
    assert len(calls) == 1
    span_from, span_to = calls[0]
    assert span_from == max(from_date, datetime.fromtimestamp(fetched_at, UTC) - timedelta(minutes=10))
    assert span_to == to_date
    assert result.total_messages == 2
    assert result.from_cache is False
    # Second run is a fresh hit now (TTL refreshed by the tail save).
    assert chat_stats.run(_params(from_date, to_date)).from_cache is True


def test_partial_past_month_extends_without_refetch(monkeypatch):
    _seed_month(
        2024,
        9,
        _september_msgs(),
        10 * 24 * 3600,
        covered_from=datetime(2024, 9, 1, tzinfo=UTC).isoformat(),
    )
    pool = [_msg(f"m{d}", datetime(2024, 9, d, 12, 0, tzinfo=UTC)) for d in range(11, 21)]
    calls: list = []
    _stub_fetch(monkeypatch, pool, calls)

    result = chat_stats.run(_params(datetime(2024, 9, 1, tzinfo=UTC), datetime(2024, 9, 20, 23, 0, tzinfo=UTC)))

    assert len(calls) == 1
    span_from, span_to = calls[0]
    assert span_from == datetime(2024, 9, 10, 12, 0, tzinfo=UTC) - timedelta(minutes=10)
    assert span_to == datetime(2024, 9, 20, 23, 0, tzinfo=UTC)
    assert result.total_messages == 20
    assert result.from_cache is False


def test_tail_overlap_dedupes_by_message_id(monkeypatch):
    _seed_month(2024, 9, _september_msgs(), 10 * 24 * 3600)
    # Overlap the seam (same id as the seeded Sep-10 message) plus new days.
    pool = [_msg("m10", datetime(2024, 9, 10, 12, 0, tzinfo=UTC), text="changed")] + [
        _msg(f"m{d}", datetime(2024, 9, d, 12, 0, tzinfo=UTC)) for d in range(11, 16)
    ]
    calls: list = []
    _stub_fetch(monkeypatch, pool, calls)

    result = chat_stats.run(_params(datetime(2024, 9, 5, tzinfo=UTC), datetime(2024, 9, 15, 23, 0, tzinfo=UTC)))

    assert len(calls) == 1
    assert result.total_messages == 11  # Sep 5..15, seam message counted once


@requires_live_month
def test_tail_refresh_preserves_truncated_flag(monkeypatch):
    from_date, to_date = _live_month_range()
    seed_ts = from_date + (to_date - from_date) / 2
    _seed_month(
        from_date.year,
        from_date.month,
        [_msg("m1", seed_ts)],
        2 * log_cache.LIVE_TTL_S + 120,
        truncated=True,
    )
    df, meta = log_cache.load_month("channel", "chan", from_date.year, from_date.month, allow_stale=True)
    assert df is not None
    meta.update({"covered_from": from_date.isoformat(), "covered_to": to_date.isoformat()})
    log_cache.save_month("channel", "chan", from_date.year, from_date.month, df, meta)

    calls: list = []
    _stub_fetch(monkeypatch, [_msg("m2", to_date - timedelta(minutes=5))], calls)
    result = chat_stats.run(_params(from_date, to_date))
    assert result.truncated is True
    assert result.total_messages == 2


def test_frame_carries_message_ids():
    df = chat_stats.messages_to_frame([_msg("abc", datetime(2024, 9, 1, 12, 0, tzinfo=UTC))])
    assert df["id"].to_list() == ["abc"]
    assert df["user_id"].to_list() == ["u"]
    assert df["role"].to_list() == ["regular"]


def _day_set(first: datetime, last: datetime) -> set:
    days: set = set()
    current = first.date()
    while current <= last.date():
        days.add(current)
        current += timedelta(days=1)
    return days


def test_quiet_month_contributes_empty_and_caches(monkeypatch):
    """A month with no logged days (calendar gap) must not kill the job."""
    year, month = 2021, 3
    days = _day_set(datetime(2021, 1, 1, tzinfo=UTC), datetime(2021, 2, 28, tzinfo=UTC))
    days |= _day_set(datetime(2021, 4, 1, tzinfo=UTC), datetime(2021, 4, 30, tzinfo=UTC))
    pool = (
        [_msg(f"j{d}", datetime(2021, 1, d, 12, 0, tzinfo=UTC)) for d in range(15, 32)]
        + [_msg(f"f{d}", datetime(2021, 2, d, 12, 0, tzinfo=UTC)) for d in range(1, 29)]
        + [_msg(f"a{d}", datetime(2021, 4, d, 12, 0, tzinfo=UTC)) for d in range(1, 16)]
    )
    calls: list = []

    async def fake_get_logs(self, channel_id_type, channel, from_date=None, to_date=None, log_params=None):
        calls.append((from_date, to_date, log_params.offset if log_params else None))
        if from_date is not None and (from_date.year, from_date.month) == (year, month):
            raise HarambelogsError("not found", status_code=404)
        assert from_date is not None and to_date is not None
        return SimpleNamespace(messages=[m for m in pool if from_date <= m.timestamp <= to_date])

    async def fake_get_list(self, channel=None, channels=None):
        return {
            "availableLogs": [{"year": str(d.year), "month": str(d.month), "day": str(d.day)} for d in days]
        }

    async def fake_emotes(channel_name, user_id):
        return {}

    monkeypatch.setattr(HarambelogsAPI, "get_channel_logs", fake_get_logs)
    monkeypatch.setattr(HarambelogsAPI, "get_list", fake_get_list)
    monkeypatch.setattr(fetcher, "fetch_channel_emotes", fake_emotes)

    params = _params(datetime(2021, 1, 15, tzinfo=UTC), datetime(2021, 4, 15, 23, 0, tzinfo=UTC))
    result = chat_stats.run(params)
    assert result.total_messages == 17 + 28 + 15
    assert result.from_cache is False

    chunk = log_cache.load_month("channel", "chan", year, month)
    assert chunk is not None
    assert chunk[0].height == 0  # quiet month cached as empty, not missing
    assert chunk[1]["complete"] is True
    assert chunk[1]["message_count"] == 0

    calls.clear()
    rerun = chat_stats.run(params)
    assert rerun.from_cache is True
    assert rerun.total_messages == result.total_messages
    assert calls == []
