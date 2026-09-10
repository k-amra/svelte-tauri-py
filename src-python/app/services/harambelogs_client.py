from datetime import datetime
from typing import Any

import httpx

from .harambelogs_models import (
    ChannelIdType,
    ChannelLogsStats,
    DateRangeParams,
    JsonLogsResponse,
    LogQueryParams,
    PreviousName,
    UserIdType,
    UserLogsStats,
)


class HarambelogsError(Exception):
    """Base exception for API errors. Carries the upstream HTTP status when known."""

    def __init__(self, message: str, status_code: int | None = None, *, empty_body: bool = False):
        super().__init__(message)
        self.status_code = status_code
        # True only for a zero-byte 2xx body: the one response shape that is
        # ambiguous between "transient blip" and "no data here" (_parse_json).
        self.empty_body = empty_body

class HarambelogsAPI:
    BASE_URL = "https://harambelogs.pl"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._external_client = client is not None
        # One client per job, shared by every page fetch: httpx pools
        # keep-alive connections internally, so pages reuse TCP/TLS sessions.
        # Limits are pinned explicitly for the concurrent page fetcher.
        self.client = client or httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=20),
            headers={"User-Agent": "TauriSidecar/1.0 (HarambelogsClient)"}
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if not self._external_client:
            await self.client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            resp = await self.client.request(method, path, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            raise HarambelogsError(
                f"API Error {e.response.status_code}: {e.response.text}",
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            raise HarambelogsError(f"Network Error: {e}") from e

    @staticmethod
    def _parse_json(resp: httpx.Response, what: str) -> Any:
        """Parse a JSON body, converting decode failures to HarambelogsError.

        Upstream occasionally answers 2xx with an empty/HTML body (hiccup,
        redirect it expects the caller to follow, proxy page). Surfacing the
        raw ``JSONDecodeError`` hides the status and the offending span, so
        translate it: retryable statuses stay retryable downstream, anything
        else fails fast with the status and a body preview.
        """
        try:
            return resp.json()
        except ValueError as e:
            if not resp.content:
                # Zero-byte 2xx bodies are transient blips (verified live: the
                # identical span returns valid JSON on retry), never "no data"
                # (out-of-range spans answer 404, quiet spans {"messages":[]}).
                # status None marks it retryable downstream; if retries also
                # come back empty, this message is the final job error.
                raise HarambelogsError(
                    f"Upstream returned an empty body for {what} (HTTP {resp.status_code})",
                    status_code=None,
                    empty_body=True,
                ) from e
            preview = (resp.text or "")[:200]
            raise HarambelogsError(
                f"Upstream returned non-JSON for {what}"
                f" (HTTP {resp.status_code}, {len(resp.content)} bytes): {preview!r}",
                status_code=resp.status_code,
            ) from e

    # --- Metadata ---
    async def get_channels(self) -> list[str]:
        resp = await self._request("GET", "/channels")
        return self._parse_json(resp, "channel list")

    async def get_capabilities(self) -> list[str]:
        resp = await self._request("GET", "/capabilities")
        return self._parse_json(resp, "capabilities")

    async def get_list(self, channel: str | None = None, channels: list[str] | None = None) -> Any:
        params = {}
        if channel:
            params["channel"] = channel
        if channels:
            params["channels"] = ",".join(channels)
        resp = await self._request("GET", "/list", params=params)
        return self._parse_json(resp, "channel list")

    async def get_name_history(self, user_id: str) -> list[PreviousName]:
        resp = await self._request("GET", f"/namehistory/{user_id}")
        return [PreviousName(**item) for item in self._parse_json(resp, f"name history for {user_id}")]

    # --- Stats ---
    async def get_user_stats(
        self, channel_id_type: ChannelIdType, channel: str,
        user_id_type: UserIdType, user: str,
        from_date: datetime | None = None, to_date: datetime | None = None
    ) -> UserLogsStats:
        params = DateRangeParams(**{"from": from_date, "to": to_date}).to_httpx_params()
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/{user_id_type}/{user}/stats", params=params)
        return UserLogsStats(**self._parse_json(resp, f"user stats for {user}"))

    async def get_channel_stats(
        self, channel_id_type: ChannelIdType, channel: str,
        from_date: datetime | None = None, to_date: datetime | None = None
    ) -> ChannelLogsStats:
        params = DateRangeParams(**{"from": from_date, "to": to_date}).to_httpx_params()
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/stats", params=params)
        return ChannelLogsStats(**self._parse_json(resp, f"channel stats for {channel}"))

    # --- Search & Logs ---
    async def search_user_logs(
        self, channel_id_type: ChannelIdType, channel: str,
        user_id_type: UserIdType, user: str, query: str,
        log_params: LogQueryParams | None = None
    ) -> JsonLogsResponse:
        params = log_params.to_httpx_params() if log_params else LogQueryParams(json_=True).to_httpx_params()
        params["q"] = query
        params["json"] = "true" # Force JSON
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/{user_id_type}/{user}/search", params=params)
        return JsonLogsResponse(**self._parse_json(resp, f"search for '{query}'"))

    async def get_channel_logs(
        self, channel_id_type: ChannelIdType, channel: str,
        from_date: datetime | None = None, to_date: datetime | None = None,
        log_params: LogQueryParams | None = None
    ) -> JsonLogsResponse:
        params = log_params.to_httpx_params() if log_params else LogQueryParams(json_=True).to_httpx_params()
        params.update(DateRangeParams(**{"from": from_date, "to": to_date}).to_httpx_params())
        params["json"] = "true"
        resp = await self._request("GET", f"/{channel_id_type}/{channel}", params=params)
        return JsonLogsResponse(
            **self._parse_json(resp, f"channel logs for {channel} [{from_date}..{to_date}]")
        )

    async def get_user_logs(
        self, channel_id_type: ChannelIdType, channel: str,
        user_id_type: UserIdType, user: str,
        from_date: datetime | None = None, to_date: datetime | None = None,
        log_params: LogQueryParams | None = None
    ) -> JsonLogsResponse:
        params = log_params.to_httpx_params() if log_params else LogQueryParams(json_=True).to_httpx_params()
        params.update(DateRangeParams(**{"from": from_date, "to": to_date}).to_httpx_params())
        params["json"] = "true"
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/{user_id_type}/{user}", params=params)
        return JsonLogsResponse(**self._parse_json(resp, f"user logs for {user}"))

    async def get_channel_logs_by_date(
        self, channel_id_type: ChannelIdType, channel: str,
        year: str, month: str, day: str,
        log_params: LogQueryParams | None = None
    ) -> JsonLogsResponse:
        params = log_params.to_httpx_params() if log_params else LogQueryParams(json_=True).to_httpx_params()
        params["json"] = "true"
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/{year}/{month}/{day}", params=params)
        return JsonLogsResponse(**self._parse_json(resp, f"channel logs for {channel} on {year}-{month}-{day}"))

    async def get_user_logs_by_month(
        self, channel_id_type: ChannelIdType, channel: str,
        user_id_type: UserIdType, user: str,
        year: str, month: str,
        log_params: LogQueryParams | None = None
    ) -> JsonLogsResponse:
        params = log_params.to_httpx_params() if log_params else LogQueryParams(json_=True).to_httpx_params()
        params["json"] = "true"
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/{user_id_type}/{user}/{year}/{month}", params=params)
        return JsonLogsResponse(**self._parse_json(resp, f"user logs for {user} in {year}-{month}"))

    # --- Random ---
    async def get_channel_random(
        self, channel_id_type: ChannelIdType, channel: str,
        log_params: LogQueryParams | None = None
    ) -> JsonLogsResponse:
        params = log_params.to_httpx_params() if log_params else LogQueryParams(json_=True).to_httpx_params()
        params["json"] = "true"
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/random", params=params)
        return JsonLogsResponse(**self._parse_json(resp, f"random logs for {channel}"))

    async def get_user_random(
        self, channel_id_type: ChannelIdType, channel: str,
        user_id_type: UserIdType, user: str,
        log_params: LogQueryParams | None = None
    ) -> JsonLogsResponse:
        params = log_params.to_httpx_params() if log_params else LogQueryParams(json_=True).to_httpx_params()
        params["json"] = "true"
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/{user_id_type}/{user}/random", params=params)
        return JsonLogsResponse(**self._parse_json(resp, f"random logs for {user}"))

    # --- Optout ---
    async def optout(self) -> str:
        resp = await self._request("POST", "/optout")
        return resp.text
