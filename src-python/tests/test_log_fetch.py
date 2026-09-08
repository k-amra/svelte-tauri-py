"""Unit tests for the paginated fetcher (stubbed API, no network)."""

import asyncio
from types import SimpleNamespace

import pytest

from app.services.harambelogs_client import HarambelogsError
from app.services.log_fetch import fetch_channel_logs


def make_msg(i: int):
    return SimpleNamespace(username=f"user{i % 10}", text=f"msg {i}", timestamp="2024-01-15T10:00:00+00:00")


class StubAPI:
    """Endless or scripted pages of `limit`-sized messages."""

    def __init__(
        self,
        total: int | None = None,
        fail_first_with: HarambelogsError | None = None,
        always_fail_with: HarambelogsError | None = None,
    ):
        self.total = total
        self.fail_first_with = fail_first_with
        self.always_fail_with = always_fail_with
        self.calls: list[tuple[int | None, int | None]] = []
        self._failed_once = False

    async def get_channel_logs(self, channel_id_type, channel, from_date, to_date, log_params):
        self.calls.append((log_params.offset, log_params.limit))
        if self.always_fail_with is not None:
            raise self.always_fail_with
        if self.fail_first_with is not None and not self._failed_once:
            self._failed_once = True
            raise self.fail_first_with
        offset = log_params.offset or 0
        limit = log_params.limit or 1000
        if self.total is None:
            return SimpleNamespace(messages=[make_msg(offset + i) for i in range(limit)])
        msgs = [make_msg(i) for i in range(offset, min(offset + limit, self.total))]
        return SimpleNamespace(messages=msgs)


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
    assert [offset for offset, _ in api.calls] == [0, 1000, 2000]
    assert seen == [0, 1, 2]  # page indices strictly increasing


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
