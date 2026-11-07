from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from app.schemas.common import Input


class TrackInput(Input):
    title: str = Field(min_length=1, max_length=300)
    artist: str = Field(min_length=1, max_length=300)
    album: str | None = Field(default=None, max_length=300)
    external_id: str | None = Field(default=None, min_length=1, max_length=200)


class EventInput(Input):
    event_id: UUID
    track: TrackInput
    observed_at: AwareDatetime
    listened_ms: int = Field(ge=0, le=86_400_000, strict=True)

    @field_validator("observed_at")
    @classmethod
    def not_future(cls, value: datetime) -> datetime:
        if value > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("관찰 시각은 현재보다 5분 이상 미래일 수 없습니다.")
        return value.astimezone(timezone.utc)


class SyncInput(Input):
    events: list[EventInput] = Field(min_length=1, max_length=100)


class EventResult(BaseModel):
    event_id: UUID
    status: Literal["accepted", "ignored_below_threshold"]
    track_id: UUID | None = None
    listened_ms: int | None = None


class SyncOut(BaseModel):
    results: list[EventResult]
