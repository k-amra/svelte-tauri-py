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

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code

class HarambelogsAPI:
    BASE_URL = "https://harambelogs.pl"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._external_client = client is not None
        self.client = client or httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
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

    # --- Metadata ---
    async def get_channels(self) -> list[str]:
        resp = await self._request("GET", "/channels")
        return resp.json()

    async def get_capabilities(self) -> list[str]:
        resp = await self._request("GET", "/capabilities")
        return resp.json()

    async def get_list(self, channel: str | None = None, channels: list[str] | None = None) -> Any:
        params = {}
        if channel:
            params["channel"] = channel
        if channels:
            params["channels"] = ",".join(channels)
        resp = await self._request("GET", "/list", params=params)
        return resp.json()

    async def get_name_history(self, user_id: str) -> list[PreviousName]:
        resp = await self._request("GET", f"/namehistory/{user_id}")
        return [PreviousName(**item) for item in resp.json()]

    # --- Stats ---
    async def get_user_stats(
        self, channel_id_type: ChannelIdType, channel: str,
        user_id_type: UserIdType, user: str,
        from_date: datetime | None = None, to_date: datetime | None = None
    ) -> UserLogsStats:
        params = DateRangeParams(**{"from": from_date, "to": to_date}).to_httpx_params()
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/{user_id_type}/{user}/stats", params=params)
        return UserLogsStats(**resp.json())

    async def get_channel_stats(
        self, channel_id_type: ChannelIdType, channel: str,
        from_date: datetime | None = None, to_date: datetime | None = None
    ) -> ChannelLogsStats:
        params = DateRangeParams(**{"from": from_date, "to": to_date}).to_httpx_params()
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/stats", params=params)
        return ChannelLogsStats(**resp.json())

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
        return JsonLogsResponse(**resp.json())

    async def get_channel_logs(
        self, channel_id_type: ChannelIdType, channel: str,
        from_date: datetime | None = None, to_date: datetime | None = None,
        log_params: LogQueryParams | None = None
    ) -> JsonLogsResponse:
        params = log_params.to_httpx_params() if log_params else LogQueryParams(json_=True).to_httpx_params()
        params.update(DateRangeParams(**{"from": from_date, "to": to_date}).to_httpx_params())
        params["json"] = "true"
        resp = await self._request("GET", f"/{channel_id_type}/{channel}", params=params)
        return JsonLogsResponse(**resp.json())

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
        return JsonLogsResponse(**resp.json())

    async def get_channel_logs_by_date(
        self, channel_id_type: ChannelIdType, channel: str,
        year: str, month: str, day: str,
        log_params: LogQueryParams | None = None
    ) -> JsonLogsResponse:
        params = log_params.to_httpx_params() if log_params else LogQueryParams(json_=True).to_httpx_params()
        params["json"] = "true"
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/{year}/{month}/{day}", params=params)
        return JsonLogsResponse(**resp.json())

    async def get_user_logs_by_month(
        self, channel_id_type: ChannelIdType, channel: str,
        user_id_type: UserIdType, user: str,
        year: str, month: str,
        log_params: LogQueryParams | None = None
    ) -> JsonLogsResponse:
        params = log_params.to_httpx_params() if log_params else LogQueryParams(json_=True).to_httpx_params()
        params["json"] = "true"
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/{user_id_type}/{user}/{year}/{month}", params=params)
        return JsonLogsResponse(**resp.json())

    # --- Random ---
    async def get_channel_random(
        self, channel_id_type: ChannelIdType, channel: str,
        log_params: LogQueryParams | None = None
    ) -> JsonLogsResponse:
        params = log_params.to_httpx_params() if log_params else LogQueryParams(json_=True).to_httpx_params()
        params["json"] = "true"
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/random", params=params)
        return JsonLogsResponse(**resp.json())

    async def get_user_random(
        self, channel_id_type: ChannelIdType, channel: str,
        user_id_type: UserIdType, user: str,
        log_params: LogQueryParams | None = None
    ) -> JsonLogsResponse:
        params = log_params.to_httpx_params() if log_params else LogQueryParams(json_=True).to_httpx_params()
        params["json"] = "true"
        resp = await self._request("GET", f"/{channel_id_type}/{channel}/{user_id_type}/{user}/random", params=params)
        return JsonLogsResponse(**resp.json())

    # --- Optout ---
    async def optout(self) -> str:
        resp = await self._request("POST", "/optout")
        return resp.text
