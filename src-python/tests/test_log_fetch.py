"""Unit tests for the paginated fetcher (stubbed API, no network)."""

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services import log_fetch
from app.services.harambelogs_client import HarambelogsError
from app.services.log_fetch import fetch_channel_logs


def make_msg(i: int):
    return SimpleNamespace(username=f"user{i % 10}", text=f"msg {i}", timestamp="2024-01-15T10:00:00+00:00")


class StubAPI:
    """Endless or scripted pages of `limit`-sized messages.

    The ``/stats`` oracle defaults to *unavailable* (raises): ambiguous
    pages then take the conservative path, so tests must opt in explicitly
    via ``stats_count`` whenever they exercise 404/empty bodies.
    """

    def __init__(
        self,
        total: int | None = None,
        fail_first_with: HarambelogsError | None = None,
        always_fail_with: HarambelogsError | None = None,
        empty_body_offsets: set[int] | None = None,
        empty_body_times: int = 0,
        stats_count: int | None = None,
        available_logs: list | None = None,
    ):
        self.total = total
        self.fail_first_with = fail_first_with
        self.always_fail_with = always_fail_with
        self.empty_body_offsets = empty_body_offsets
        self.empty_body_times = empty_body_times
        self.stats_count = stats_count
        self.available_logs = available_logs
        self.calls: list[tuple[int | None, int | None]] = []
        self.stats_calls: list = []
        self.list_calls: list = []
        self._failed_once = False

    async def get_channel_logs(self, channel_id_type, channel, from_date, to_date, log_params):
        self.calls.append((log_params.offset, log_params.limit))
        if self.always_fail_with is not None:
            raise self.always_fail_with
        if self.fail_first_with is not None and not self._failed_once:
            self._failed_once = True
            raise self.fail_first_with
        offset = log_params.offset or 0
        if self.empty_body_times > 0:
            self.empty_body_times -= 1
            raise HarambelogsError("Upstream returned an empty body", status_code=None, empty_body=True)
        if self.empty_body_offsets is not None and offset in self.empty_body_offsets:
            raise HarambelogsError("Upstream returned an empty body", status_code=None, empty_body=True)
        limit = log_params.limit or 1000
        if self.total is None:
            return SimpleNamespace(messages=[make_msg(offset + i) for i in range(limit)])
        msgs = [make_msg(i) for i in range(offset, min(offset + limit, self.total))]
        return SimpleNamespace(messages=msgs)

    async def get_channel_stats(self, channel_id_type, channel, from_date=None, to_date=None):
        self.stats_calls.append((from_date, to_date))
        if self.stats_count is None:
            raise HarambelogsError("stats oracle unavailable", status_code=503)
        return SimpleNamespace(messageCount=self.stats_count)

    async def get_list(self, channel=None, channels=None):
        self.list_calls.append((channel, channels))
        if self.available_logs is None:
            raise HarambelogsError("list unavailable", status_code=503)
        return {"availableLogs": self.available_logs}


def run_fetch(api, **kwargs):
    return asyncio.run(fetch_channel_logs(api, "channel", "chan", **kwargs))


def test_pagination_multiple_pages():
    api = StubAPI(total=2500)
    seen: list[int] = []
    messages, truncated = run_fetch(
        api, on_page=lambda page, msgs: seen.append(page)
    )
    assert len(messages) == 2500
    assert truncated is False
    offsets = [offset for offset, _ in api.calls]
    assert offsets[0] == 0  # slow-start: first request is always offset 0
    assert len(set(offsets)) == len(offsets)  # each page fetched exactly once
    assert {0, 1000, 2000} <= set(offsets)  # all real pages covered
    # Anything beyond is bounded tail over-fetch: extra in-flight requests
    # issued before the short page arrived, all landing past the data end.
    assert all(o is not None and o % 1000 == 0 for o in offsets)
    assert all(o >= 3000 for o in offsets[3:])
    assert sorted(seen) == sorted(o // 1000 for o in offsets)


def test_empty_first_page():
    api = StubAPI(total=0)
    messages, truncated = run_fetch(api)
    assert messages == []
    assert truncated is False
    assert len(api.calls) == 1


def test_truncation_cap():
    api = StubAPI(total=None)  # endless
    messages, truncated = run_fetch(api, max_pages=2)
    assert len(messages) == 2000
    assert truncated is True


def test_retry_then_success():
    api = StubAPI(total=10, fail_first_with=HarambelogsError("rate limited", status_code=429))
    messages, truncated = run_fetch(api)
    assert len(messages) == 10
    assert truncated is False
    assert len(api.calls) == 2


def test_non_retryable_raises_immediately():
    api = StubAPI(always_fail_with=HarambelogsError("not found", status_code=404))
    with pytest.raises(HarambelogsError):
        run_fetch(api)
    assert len(api.calls) == 1


class PastEnd404API(StubAPI):
    """Upstream 404s once the offset runs past the last message of the span."""

    def __init__(self, total: int, end_offset: int, stats_count: int | None = None):
        super().__init__(total=total, stats_count=stats_count)
        self.end_offset = end_offset

    async def get_channel_logs(self, channel_id_type, channel, from_date, to_date, log_params):
        self.calls.append((log_params.offset, log_params.limit))
        offset = log_params.offset or 0
        if offset >= self.end_offset:
            raise HarambelogsError("not found", status_code=404)
        limit = log_params.limit or 1000
        msgs = [make_msg(i) for i in range(offset, min(offset + limit, self.total))]
        return SimpleNamespace(messages=msgs)


def test_404_past_end_keeps_downloaded_messages():
    # Oracle confirms offset >= count: genuinely past the end, not a refusal.
    api = PastEnd404API(total=2500, end_offset=3000, stats_count=2500)
    seen: list[int] = []
    messages, truncated = run_fetch(api, on_page=lambda page, msgs: seen.append(page))
    assert len(messages) == 2500
    assert [m.text for m in messages] == [f"msg {i}" for i in range(2500)]
    assert truncated is False
    assert {offset for offset, _ in api.calls} >= {0, 1000, 2000}
    assert sorted(seen) == sorted(offset // 1000 for offset, _ in api.calls)


def test_garbled_body_error_is_not_retried():
    # Non-empty garbage with a 200 status means upstream confusion, not a
    # blip: fail fast instead of hammering upstream. (Zero-byte bodies use
    # status None and *are* retried; see below.)
    api = StubAPI(
        always_fail_with=HarambelogsError("Upstream returned non-JSON (HTTP 200)", status_code=200)
    )
    with pytest.raises(HarambelogsError, match="non-JSON"):
        run_fetch(api)
    assert len(api.calls) == 1


def test_empty_body_oracle_down_retries_then_raises(monkeypatch):
    # Oracle unreachable (default stub): empty bodies take the legacy backoff
    # path and fail loud on exhaustion — never synthesized as data.
    monkeypatch.setattr(log_fetch, "RETRY_BACKOFF_BASE_S", 0.01)
    monkeypatch.setattr(log_fetch, "RETRY_BACKOFF_CAP_S", 0.02)
    api = StubAPI(always_fail_with=HarambelogsError("Upstream returned an empty body", status_code=None))
    with pytest.raises(HarambelogsError, match="empty body"):
        run_fetch(api)
    assert len(api.calls) == 1 + log_fetch.MAX_RETRIES


class LaggyAPI(StubAPI):
    """Second page responds slowly so a later page completes first."""

    async def get_channel_logs(self, channel_id_type, channel, from_date, to_date, log_params):
        if (log_params.offset or 0) == 1000:
            await asyncio.sleep(0.3)
        return await super().get_channel_logs(channel_id_type, channel, from_date, to_date, log_params)


def test_out_of_order_pages_merge_in_offset_order():
    api = LaggyAPI(total=2500)
    seen: list[int] = []
    messages, truncated = run_fetch(
        api, on_page=lambda page, msgs: seen.append(page)
    )
    assert truncated is False
    assert seen == [0, 2, 1]  # page 1 lags behind page 2
    # Merged frame is in global offset order despite completion order.
    assert [m.text for m in messages] == [f"msg {i}" for i in range(2500)]


def test_small_channel_costs_a_single_request():
    # Slow-start: no speculative burst, so a sub-page channel fetches once.
    api = StubAPI(total=10)
    messages, truncated = run_fetch(api)
    assert len(messages) == 10
    assert truncated is False
    assert [offset for offset, _ in api.calls] == [0]


def test_channel_log_days_parses_calendar():
    from datetime import date as _date

    api = StubAPI(
        available_logs=[
            {"year": "2024", "month": "1", "day": "5"},
            {"year": 2024, "month": 1, "day": 6},
            {"nope": True},
            {"year": "2024", "month": 13, "day": "1"},
            "garbage",
        ]
    )
    assert asyncio.run(log_fetch.channel_log_days(api, "channel", "chan")) == {
        _date(2024, 1, 5),
        _date(2024, 1, 6),
    }
    assert len(api.list_calls) == 1


def test_channel_log_days_empty_or_broken_is_none():
    assert asyncio.run(log_fetch.channel_log_days(StubAPI(available_logs=[]), "channel", "chan")) is None
    assert asyncio.run(log_fetch.channel_log_days(StubAPI(), "channel", "chan")) is None

    class BadShape(StubAPI):
        async def get_list(self, channel=None, channels=None):
            return ["not", "a", "dict"]

    assert asyncio.run(log_fetch.channel_log_days(BadShape(), "channel", "chan")) is None


def test_offset_zero_404_outside_logged_days_is_empty():
    # Pre-history span with a calendar proving the channel exists.
    api = StubAPI(
        always_fail_with=HarambelogsError("not found", status_code=404),
        available_logs=[{"year": "2024", "month": "6", "day": "1"}],
    )
    messages, truncated = asyncio.run(
        fetch_channel_logs(api, "channel", "chan", datetime(2024, 1, 1), datetime(2024, 2, 1))
    )
    assert messages == []
    assert truncated is False
    assert len(api.list_calls) == 1


def test_offset_zero_404_overlapping_logged_days_raises():
    api = StubAPI(
        always_fail_with=HarambelogsError("not found", status_code=404),
        available_logs=[{"year": "2024", "month": "1", "day": "15"}],
    )
    with pytest.raises(HarambelogsError, match="not found"):
        asyncio.run(fetch_channel_logs(api, "channel", "chan", datetime(2024, 1, 1), datetime(2024, 2, 1)))


def test_offset_zero_404_empty_calendar_raises():
    # No calendar = possibly a typo'd channel: stay loud, never zero-stats.
    api = StubAPI(
        always_fail_with=HarambelogsError("not found", status_code=404),
        available_logs=[],
    )
    with pytest.raises(HarambelogsError, match="not found"):
        asyncio.run(fetch_channel_logs(api, "channel", "chan", datetime(2024, 1, 1), datetime(2024, 2, 1)))


def test_quiet_span_empty_body_stops_immediately():
    # Oracle says count 0: genuinely no data — one probe, no retry storm.
    api = StubAPI(empty_body_offsets={0}, stats_count=0)
    messages, truncated = run_fetch(api)
    assert messages == []
    assert truncated is False
    assert len(api.calls) == 1
    assert len(api.stats_calls) == 1


def test_past_end_empty_body_keeps_messages():
    # Empty-body flavor of past-the-end (oracle: offset >= count).
    api = StubAPI(total=2500, empty_body_offsets={3000, 4000}, stats_count=2500)
    messages, truncated = run_fetch(api)
    assert [m.text for m in messages] == [f"msg {i}" for i in range(2500)]
    assert truncated is False


def test_blip_empty_body_with_data_retries_once():
    # Oracle confirms data behind the offset: one immediate retry, no split.
    api = StubAPI(total=2500, empty_body_times=1, stats_count=2500)
    messages, truncated = run_fetch(api)
    assert [m.text for m in messages] == [f"msg {i}" for i in range(2500)]
    assert truncated is False
    assert sum(1 for offset, _ in api.calls if offset == 0) == 2
    assert len(api.stats_calls) == 1  # probed once, memoized for the retry


class SplitStubAPI:
    """Upstream refusing deep offsets: 404 past `refuse_at` (per call).

    Serves message totals proportional to each call's time span (like real
    upstream), content-keyed by span start so time-split halves stay
    distinguishable after the merge.
    """

    def __init__(self, refuse_at: int, root_from, root_to, root_total: int):
        self.refuse_at = refuse_at
        self.root_from = root_from
        self.root_to = root_to
        self.root_total = root_total
        self.calls: list = []
        self.stats_calls: list = []

    def _total_for(self, from_date, to_date) -> int:
        if from_date is None or to_date is None or to_date <= from_date:
            return self.root_total
        frac = (to_date - from_date) / (self.root_to - self.root_from)
        return int(round(self.root_total * frac))

    async def get_channel_logs(self, channel_id_type, channel, from_date, to_date, log_params):
        self.calls.append((from_date, to_date, log_params.offset, log_params.limit))
        offset = log_params.offset or 0
        if offset >= self.refuse_at:
            raise HarambelogsError("deep pagination refused", status_code=404)
        limit = log_params.limit or 1000
        total = self._total_for(from_date, to_date)
        base = from_date.isoformat() if from_date is not None else "none"
        msgs = [
            SimpleNamespace(username="u", text=f"{base}#{offset + i}", timestamp="2024-01-15T10:00:00+00:00")
            for i in range(max(0, min(limit, total - offset)))
        ]
        return SimpleNamespace(messages=msgs)

    async def get_channel_stats(self, channel_id_type, channel, from_date=None, to_date=None):
        self.stats_calls.append((from_date, to_date))
        return SimpleNamespace(messageCount=self.root_total)


def _prefixes(texts: list[str]) -> set[str]:
    return {t.split("#")[0] for t in texts}


def test_deep_refusal_splits_span_and_merges_in_order():
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    start = _dt(2024, 1, 1, tzinfo=_UTC)
    mid = _dt(2024, 1, 16, tzinfo=_UTC)
    end = _dt(2024, 1, 31, tzinfo=_UTC)
    q1 = start + (mid - start) / 2
    q3 = mid + (end - mid) / 2
    api = SplitStubAPI(refuse_at=20000, root_from=start, root_to=end, root_total=60000)
    messages, truncated = asyncio.run(fetch_channel_logs(api, "channel", "chan", start, end))
    assert truncated is False
    assert len(messages) == 60000
    assert len({m.text for m in messages}) == 60000  # halves distinct, no collapse
    first_half = [m.text for m in messages[:30000]]
    second_half = [m.text for m in messages[30000:]]
    assert _prefixes(first_half) == {start.isoformat(), q1.isoformat()}
    assert _prefixes(second_half) == {mid.isoformat(), q3.isoformat()}


def test_small_refusal_splits_once():
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    start = _dt(2024, 1, 1, tzinfo=_UTC)
    end = _dt(2024, 1, 31, tzinfo=_UTC)
    api = SplitStubAPI(refuse_at=500, root_from=start, root_to=end, root_total=3000)
    messages, truncated = asyncio.run(fetch_channel_logs(api, "channel", "chan", start, end))
    assert truncated is False
    assert len(messages) == 3000
    assert len({m.text for m in messages}) == 3000


def test_split_depth_cap_fails_loud(monkeypatch):
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    monkeypatch.setattr(log_fetch, "MAX_SPLIT_DEPTH", 0)
    start = _dt(2024, 1, 1, tzinfo=_UTC)
    end = _dt(2024, 1, 31, tzinfo=_UTC)
    api = SplitStubAPI(refuse_at=20000, root_from=start, root_to=end, root_total=60000)
    with pytest.raises(HarambelogsError, match="refuses deep pagination"):
        asyncio.run(fetch_channel_logs(api, "channel", "chan", start, end))
    # Only the root span was attempted — no split fetches happened.
    spans = {(f, t) for f, t, _, _ in api.calls}
    assert spans == {(start, end)}
