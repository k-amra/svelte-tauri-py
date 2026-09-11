"""Tests for the chat_stats monthly-chunk cache (fetch stubbed, disk real)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core import paths
from app.scripts import chat_stats
from app.services import log_cache
from app.services.harambelogs_client import HarambelogsError
from app.services.harambelogs_models import FullMessage


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path):
    paths.init(str(tmp_path))


@pytest.fixture(autouse=True)
def _no_calendar(monkeypatch):
    """Keep these tests offline: no /list probe unless a test opts in."""

    async def _none(api, channel_id_type, channel):
        return None

    monkeypatch.setattr(chat_stats, "channel_log_days", _none)


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


def _september_pool() -> list[FullMessage]:
    return [_msg(f"s{d}", datetime(2024, 9, d, 12, 0, tzinfo=UTC)) for d in range(1, 31)]


def _october_pool() -> list[FullMessage]:
    return [_msg(f"o{d}", datetime(2024, 10, d, 12, 0, tzinfo=UTC)) for d in range(1, 6)]


def _stub_fetch(monkeypatch, pool: list[FullMessage], calls: list):
    async def fake_fetch(api, channel_id_type, channel, from_date, to_date, **kwargs):
        calls.append((from_date, to_date))
        return [m for m in pool if from_date <= m.timestamp <= to_date], False

    async def fake_emotes(channel_name, user_id):
        return {}

    monkeypatch.setattr(chat_stats, "fetch_channel_logs", fake_fetch)
    monkeypatch.setattr(chat_stats, "fetch_channel_emotes", fake_emotes)


def _params(from_date: datetime, to_date: datetime, **overrides):
    base = {"channel": "chan", "from_date": from_date, "to_date": to_date}
    base.update(overrides)
    return chat_stats.Params(**base)


def test_second_run_hits_cache_and_force_bypasses(monkeypatch):
    calls: list = []
    _stub_fetch(monkeypatch, _september_pool(), calls)

    params = _params(datetime(2024, 9, 1, tzinfo=UTC), datetime(2024, 9, 10, 23, 0, tzinfo=UTC))
    r1 = chat_stats.run(params)
    assert r1.from_cache is False
    assert r1.total_messages == 10
    assert len(calls) == 1

    r2 = chat_stats.run(params)
    assert r2.from_cache is True
    assert r2.cached_at is not None
    assert len(calls) == 1
    assert r2.total_messages == r1.total_messages

    chat_stats.run(_params(**{**params.model_dump(), "force_refresh": True}))
    assert len(calls) == 2


def test_force_refresh_merges_without_double_counting(monkeypatch):
    """Refresh re-fetches the span but dedupes by id: totals stay stable."""
    calls: list = []
    _stub_fetch(monkeypatch, _september_pool(), calls)

    params = _params(datetime(2024, 9, 1, tzinfo=UTC), datetime(2024, 9, 10, 23, 0, tzinfo=UTC))
    r1 = chat_stats.run(params)
    assert r1.total_messages == 10

    r2 = chat_stats.run(_params(**{**params.model_dump(), "force_refresh": True}))
    assert r2.from_cache is False
    assert r2.total_messages == 10
    assert len(calls) == 2


def test_to_date_is_exclusive(monkeypatch):
    """A message timestamped exactly at to_date is excluded (half-open range)."""
    calls: list = []
    pool = _september_pool() + [
        FullMessage(
            type=0,
            text="boundary",
            displayName="u",
            timestamp=datetime(2024, 9, 10, 23, 0, tzinfo=UTC),
            id="edge",
            tags={},
            username="u",
            channel="chan",
            raw="boundary",
        )
    ]
    _stub_fetch(monkeypatch, pool, calls)

    result = chat_stats.run(_params(datetime(2024, 9, 1, tzinfo=UTC), datetime(2024, 9, 10, 23, 0, tzinfo=UTC)))
    assert result.total_messages == 10


def test_shifted_range_within_month_reuses_chunk(monkeypatch):
    """1.09–10.09 then 2.09–10.09: the second run downloads nothing."""
    calls: list = []
    _stub_fetch(monkeypatch, _september_pool(), calls)

    r1 = chat_stats.run(_params(datetime(2024, 9, 1, tzinfo=UTC), datetime(2024, 9, 10, 23, 0, tzinfo=UTC)))
    assert r1.total_messages == 10

    r2 = chat_stats.run(_params(datetime(2024, 9, 2, tzinfo=UTC), datetime(2024, 9, 10, 23, 0, tzinfo=UTC)))
    assert r2.from_cache is True
    assert r2.total_messages == 9
    assert len(calls) == 1


def test_extended_range_downloads_only_the_new_month(monkeypatch):
    calls: list = []
    _stub_fetch(monkeypatch, _september_pool() + _october_pool(), calls)

    r1 = chat_stats.run(_params(datetime(2024, 9, 1, tzinfo=UTC), datetime(2024, 10, 1, tzinfo=UTC)))
    assert r1.total_messages == 30
    assert len(calls) == 1

    r2 = chat_stats.run(_params(datetime(2024, 9, 1, tzinfo=UTC), datetime(2024, 10, 5, 23, 0, tzinfo=UTC)))
    assert r2.from_cache is False  # October had to be downloaded
    assert r2.total_messages == 35
    assert len(calls) == 2
    span_from, span_to = calls[1]
    assert span_from == datetime(2024, 10, 1, tzinfo=UTC)
    assert span_to == datetime(2024, 10, 5, 23, 0, tzinfo=UTC)


def test_span_failure_names_the_month(monkeypatch):
    async def boom(api, channel_id_type, channel, from_date, to_date, **kwargs):
        raise HarambelogsError("API Error 404: not found", status_code=404)

    async def fake_emotes(channel_name, user_id):
        return {}

    monkeypatch.setattr(chat_stats, "fetch_channel_logs", boom)
    monkeypatch.setattr(chat_stats, "fetch_channel_emotes", fake_emotes)
    with pytest.raises(HarambelogsError, match=r"\[2024-09"):
        chat_stats.run(_params(datetime(2024, 9, 1, tzinfo=UTC), datetime(2024, 9, 5, tzinfo=UTC)))


def test_transient_span_failure_retries_span(monkeypatch):
    """A blip killing a span mid-month retries the span instead of the job."""
    monkeypatch.setattr(chat_stats, "SPAN_RETRY_COOLDOWN_S", 0.01)
    attempts: list = []

    async def flaky(api, channel_id_type, channel, from_date, to_date, **kwargs):
        attempts.append((from_date, to_date))
        if len(attempts) == 1:
            raise HarambelogsError("Upstream returned an empty body", status_code=None)
        return [_msg("m1", datetime(2024, 9, 1, 12, 0, tzinfo=UTC))], False

    async def fake_emotes(channel_name, user_id):
        return {}

    monkeypatch.setattr(chat_stats, "fetch_channel_logs", flaky)
    monkeypatch.setattr(chat_stats, "fetch_channel_emotes", fake_emotes)

    result = chat_stats.run(_params(datetime(2024, 9, 1, tzinfo=UTC), datetime(2024, 9, 2, tzinfo=UTC)))
    assert result.total_messages == 1
    assert result.from_cache is False
    assert len(attempts) == 2
    assert attempts[0] == attempts[1]  # same span retried from offset 0


def test_persistent_span_failure_names_the_month(monkeypatch):
    monkeypatch.setattr(chat_stats, "SPAN_RETRY_COOLDOWN_S", 0.01)
    attempts: list = []

    async def dead(api, channel_id_type, channel, from_date, to_date, **kwargs):
        attempts.append((from_date, to_date))
        raise HarambelogsError("API Error 503: down", status_code=503)

    async def fake_emotes(channel_name, user_id):
        return {}

    monkeypatch.setattr(chat_stats, "fetch_channel_logs", dead)
    monkeypatch.setattr(chat_stats, "fetch_channel_emotes", fake_emotes)
    with pytest.raises(HarambelogsError, match=r"\[2024-09"):
        chat_stats.run(_params(datetime(2024, 9, 1, tzinfo=UTC), datetime(2024, 9, 2, tzinfo=UTC)))
    assert len(attempts) == 2  # initial + one span retry


def test_range_clamped_to_logged_history(monkeypatch):
    """From predating the channel never hits the network (clamped once)."""
    first_day = datetime(2020, 8, 20, tzinfo=UTC)
    days: set = set()
    current = first_day
    end_day = datetime(2024, 9, 10, tzinfo=UTC)
    while current <= end_day:
        days.add(current.date())
        current += timedelta(days=1)

    cal_calls: list = []

    async def fake_days(api, channel_id_type, channel):
        cal_calls.append(1)
        return set(days)

    pool = [_msg(f"s{d}", datetime(2024, 9, d, 12, 0, tzinfo=UTC)) for d in range(1, 6)]
    calls: list = []
    _stub_fetch(monkeypatch, pool, calls)
    # Override the file's offline fixture: this test opts into the calendar.
    monkeypatch.setattr(chat_stats, "channel_log_days", fake_days)

    notes: list = []
    params = _params(
        datetime(2020, 1, 1, tzinfo=UTC), datetime(2024, 9, 5, 23, 0, tzinfo=UTC), max_range_days=2000
    )
    result = chat_stats.run(params, progress=lambda pct, msg="": notes.append(msg))

    assert result.total_messages == 5
    assert result.from_cache is False
    assert all(span_from >= first_day for span_from, _ in calls)
    assert any("clamped to logged history" in msg for msg in notes)

    # Repeat: no fetches. Exactly one cheap calendar probe remains: phase 1
    # checks the unclamped months (it can't know the clamp without the
    # calendar), then clamping finds nothing left to download.
    calls.clear()
    cal_calls.clear()
    rerun = chat_stats.run(params)
    assert rerun.from_cache is True
    assert rerun.total_messages == 5
    assert calls == []
    assert cal_calls == [1]


def test_disjoint_ranges_fetch_only_the_gap(monkeypatch):
    """Sep 1–5 then Sep 20–25: the second run fetches exactly its span
    (no 15-day bridge), and a later Sep 1–25 run fills only the middle."""
    calls: list = []
    _stub_fetch(monkeypatch, _september_pool(), calls)

    r1 = chat_stats.run(_params(datetime(2024, 9, 1, tzinfo=UTC), datetime(2024, 9, 5, 23, 0, tzinfo=UTC)))
    assert r1.total_messages == 5

    r2 = chat_stats.run(_params(datetime(2024, 9, 20, tzinfo=UTC), datetime(2024, 9, 25, 23, 0, tzinfo=UTC)))
    assert r2.total_messages == 6
    assert r2.from_cache is False
    assert calls[-1] == (datetime(2024, 9, 20, tzinfo=UTC), datetime(2024, 9, 25, 23, 0, tzinfo=UTC))

    _, meta = log_cache.load_month("channel", "chan", 2024, 9)
    assert meta["coverage"] == [
        ["2024-09-01T00:00:00+00:00", "2024-09-05T23:00:00+00:00"],
        ["2024-09-20T00:00:00+00:00", "2024-09-25T23:00:00+00:00"],
    ]

    r3 = chat_stats.run(_params(datetime(2024, 9, 1, tzinfo=UTC), datetime(2024, 9, 25, 23, 0, tzinfo=UTC)))
    assert r3.total_messages == 25
    assert calls[-1] == (datetime(2024, 9, 5, 22, 50, tzinfo=UTC), datetime(2024, 9, 20, 0, 10, tzinfo=UTC))


def test_get_months_range():
    assert chat_stats._get_months_range(datetime(2024, 1, 15, tzinfo=UTC), datetime(2024, 1, 20, tzinfo=UTC)) == [
        (2024, 1)
    ]
    assert chat_stats._get_months_range(datetime(2024, 1, 15, tzinfo=UTC), datetime(2024, 3, 2, tzinfo=UTC)) == [
        (2024, 1),
        (2024, 2),
        (2024, 3),
    ]
    assert chat_stats._get_months_range(datetime(2024, 12, 30, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)) == [
        (2024, 12),
        (2025, 1),
    ]
