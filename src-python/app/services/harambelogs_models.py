from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Literal, Any
from datetime import datetime

# Enums based on API docs
ChannelIdType = Literal["channel", "channelid"]
UserIdType = Literal["user", "userid"]

class PreviousName(BaseModel):
    user_login: str
    last_timestamp: datetime
    first_timestamp: datetime

class FullMessage(BaseModel):
    type: int
    text: str
    displayName: str
    timestamp: datetime
    id: str
    tags: dict[str, Any]
    username: str
    channel: str
    raw: str

class JsonLogsResponse(BaseModel):
    messages: list[FullMessage]

class UserLogsStats(BaseModel):
    userId: str
    userLogin: Optional[str] = None
    messageCount: int

class TopChatter(BaseModel):
    userId: str
    userLogin: Optional[str] = None
    messageCount: int

class ChannelLogsStats(BaseModel):
    messageCount: int
    topChatters: list[TopChatter]

class LogQueryParams(BaseModel):
    """Handles the complex boolean/pagination query parameters."""
    model_config = ConfigDict(populate_by_name=True)

    json_: bool = Field(True, alias="json")
    jsonBasic: bool = False
    raw: bool = False
    reverse: bool = False
    ndjson: bool = False
    limit: Optional[int] = Field(None, ge=0)
    offset: Optional[int] = Field(None, ge=0)

    def to_httpx_params(self) -> dict:
        dump = self.model_dump(by_alias=True, exclude_none=True)
        params = {}
        for k, v in dump.items():
            if isinstance(v, bool):
                if v: params[k] = "true"  # Only send if True
            else:
                params[k] = v
        return params

class DateRangeParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    
    from_: Optional[datetime] = Field(None, alias="from")
    to: Optional[datetime] = None

    def to_httpx_params(self) -> dict:
        dump = self.model_dump(by_alias=True, exclude_none=True)
        for k, v in dump.items():
            if isinstance(v, datetime):
                dump[k] = v.isoformat()  # RFC 3339 format
        return dump