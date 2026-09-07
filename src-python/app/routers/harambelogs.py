from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime

from app.services.harambelogs_client import HarambelogsAPI, HarambelogsError
from app.services.harambelogs_models import (
    JsonLogsResponse, LogQueryParams, PreviousName, 
    UserLogsStats, ChannelLogsStats, ChannelIdType, UserIdType
)

router = APIRouter()

def _log_params(limit: int, offset: Optional[int], reverse: bool) -> LogQueryParams:
    return LogQueryParams(limit=limit, offset=offset, reverse=reverse, json_=True)

@router.get("/channels", response_model=list[str])
async def get_channels():
    async with HarambelogsAPI() as api:
        try: return await api.get_channels()
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e

@router.get("/capabilities", response_model=list[str])
async def get_capabilities():
    async with HarambelogsAPI() as api:
        try: return await api.get_capabilities()
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e

@router.get("/list")
async def get_list(channel: Optional[str] = None, channels: Optional[str] = None):
    async with HarambelogsAPI() as api:
        try:
            ch_list = channels.split(",") if channels else None
            return await api.get_list(channel=channel, channels=ch_list)
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e

@router.get("/namehistory/{user_id}", response_model=list[PreviousName])
async def get_name_history(user_id: str):
    async with HarambelogsAPI() as api:
        try: return await api.get_name_history(user_id)
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e

@router.get("/stats/user/{channel_id_type}/{channel}/{user_id_type}/{user}", response_model=UserLogsStats)
async def get_user_stats(
    channel_id_type: ChannelIdType, channel: str, user_id_type: UserIdType, user: str,
    from_date: Optional[datetime] = Query(None, alias="from"), to_date: Optional[datetime] = Query(None, alias="to")
):
    async with HarambelogsAPI() as api:
        try: return await api.get_user_stats(channel_id_type, channel, user_id_type, user, from_date, to_date)
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e

@router.get("/stats/channel/{channel_id_type}/{channel}", response_model=ChannelLogsStats)
async def get_channel_stats(
    channel_id_type: ChannelIdType, channel: str,
    from_date: Optional[datetime] = Query(None, alias="from"), to_date: Optional[datetime] = Query(None, alias="to")
):
    async with HarambelogsAPI() as api:
        try: return await api.get_channel_stats(channel_id_type, channel, from_date, to_date)
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e

@router.get("/search/{channel_id_type}/{channel}/{user_id_type}/{user}", response_model=JsonLogsResponse)
async def search_logs(
    channel_id_type: ChannelIdType, channel: str, user_id_type: UserIdType, user: str,
    q: str = Query(..., min_length=1), limit: int = Query(50, ge=1, le=1000),
    offset: Optional[int] = Query(None, ge=0), reverse: bool = Query(False)
):
    async with HarambelogsAPI() as api:
        try: return await api.search_user_logs(channel_id_type, channel, user_id_type, user, q, _log_params(limit, offset, reverse))
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e

@router.get("/logs/channel/{channel_id_type}/{channel}", response_model=JsonLogsResponse)
async def get_channel_logs(
    channel_id_type: ChannelIdType, channel: str,
    from_date: Optional[datetime] = Query(None, alias="from"), to_date: Optional[datetime] = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=1000), offset: Optional[int] = Query(None, ge=0), reverse: bool = Query(False)
):
    async with HarambelogsAPI() as api:
        try: return await api.get_channel_logs(channel_id_type, channel, from_date, to_date, _log_params(limit, offset, reverse))
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e

@router.get("/logs/user/{channel_id_type}/{channel}/{user_id_type}/{user}", response_model=JsonLogsResponse)
async def get_user_logs(
    channel_id_type: ChannelIdType, channel: str, user_id_type: UserIdType, user: str,
    from_date: Optional[datetime] = Query(None, alias="from"), to_date: Optional[datetime] = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=1000), offset: Optional[int] = Query(None, ge=0), reverse: bool = Query(False)
):
    async with HarambelogsAPI() as api:
        try: return await api.get_user_logs(channel_id_type, channel, user_id_type, user, from_date, to_date, _log_params(limit, offset, reverse))
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e

@router.get("/logs/channel/{channel_id_type}/{channel}/{year}/{month}/{day}", response_model=JsonLogsResponse)
async def get_channel_logs_by_date(
    channel_id_type: ChannelIdType, channel: str, year: str, month: str, day: str,
    limit: int = Query(50, ge=1, le=1000), offset: Optional[int] = Query(None, ge=0), reverse: bool = Query(False)
):
    async with HarambelogsAPI() as api:
        try: return await api.get_channel_logs_by_date(channel_id_type, channel, year, month, day, _log_params(limit, offset, reverse))
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e

@router.get("/logs/user/{channel_id_type}/{channel}/{user_id_type}/{user}/{year}/{month}", response_model=JsonLogsResponse)
async def get_user_logs_by_month(
    channel_id_type: ChannelIdType, channel: str, user_id_type: UserIdType, user: str, year: str, month: str,
    limit: int = Query(50, ge=1, le=1000), offset: Optional[int] = Query(None, ge=0), reverse: bool = Query(False)
):
    async with HarambelogsAPI() as api:
        try: return await api.get_user_logs_by_month(channel_id_type, channel, user_id_type, user, year, month, _log_params(limit, offset, reverse))
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e

@router.get("/random/channel/{channel_id_type}/{channel}", response_model=JsonLogsResponse)
async def get_channel_random(
    channel_id_type: ChannelIdType, channel: str,
    limit: int = Query(1, ge=1, le=100), offset: Optional[int] = Query(None, ge=0), reverse: bool = Query(False)
):
    async with HarambelogsAPI() as api:
        try: return await api.get_channel_random(channel_id_type, channel, _log_params(limit, offset, reverse))
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e

@router.get("/random/user/{channel_id_type}/{channel}/{user_id_type}/{user}", response_model=JsonLogsResponse)
async def get_user_random(
    channel_id_type: ChannelIdType, channel: str, user_id_type: UserIdType, user: str,
    limit: int = Query(1, ge=1, le=100), offset: Optional[int] = Query(None, ge=0), reverse: bool = Query(False)
):
    async with HarambelogsAPI() as api:
        try: return await api.get_user_random(channel_id_type, channel, user_id_type, user, _log_params(limit, offset, reverse))
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e

@router.post("/optout")
async def optout():
    async with HarambelogsAPI() as api:
        try: return {"message": await api.optout()}
        except HarambelogsError as e: raise HTTPException(status_code=400, detail=str(e)) from e