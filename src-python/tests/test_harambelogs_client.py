"""Tests for defensive upstream JSON parsing (mocked transport, no network)."""

import asyncio
import json

import httpx
import pytest

from app.services.harambelogs_client import HarambelogsAPI, HarambelogsError


def _api(handler) -> HarambelogsAPI:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url=HarambelogsAPI.BASE_URL)
    return HarambelogsAPI(client=client)


async def _get_logs(api: HarambelogsAPI):
    try:
        return await api.get_channel_logs("channel", "chan", None, None)
    finally:
        await api.client.aclose()


def test_empty_body_becomes_retryable_error_not_decode_error():
    # Zero-byte bodies are transient blips: signal retryable (status None)
    # instead of failing fast, so the fetcher's backoff absorbs them.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"", request=request)

    with pytest.raises(HarambelogsError, match="empty body") as exc_info:
        asyncio.run(_get_logs(_api(handler)))
    assert exc_info.value.status_code is None
    assert "HTTP 200" in str(exc_info.value)


def test_html_body_includes_preview():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html><body>proxy page</body></html>", request=request)

    with pytest.raises(HarambelogsError, match="non-JSON") as exc_info:
        asyncio.run(_get_logs(_api(handler)))
    assert "proxy page" in str(exc_info.value)


def test_redirect_surfaces_with_status():
    # httpx raises on unfollowed 3xx before parsing, so a redirect already
    # arrives as HarambelogsError (fail fast: resending won't help).
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(303, content=b"", headers={"location": "/login"}, request=request)

    with pytest.raises(HarambelogsError, match="API Error 303") as exc_info:
        asyncio.run(_get_logs(_api(handler)))
    assert exc_info.value.status_code == 303


def test_error_status_still_reports_status_first():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"<html>down</html>", request=request)

    with pytest.raises(HarambelogsError, match="API Error 503") as exc_info:
        asyncio.run(_get_logs(_api(handler)))
    assert exc_info.value.status_code == 503


def test_valid_json_still_parses():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"messages": []}).encode(), request=request)

    resp = asyncio.run(_get_logs(_api(handler)))
    assert resp.messages == []
