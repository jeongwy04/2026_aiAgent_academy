from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(Input):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)

    @field_validator("password", mode="before")
    @classmethod
    def preserve_password(cls, value):
        # Passwords are opaque: surrounding spaces are part of the secret.
        return value

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


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


class TrackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    artist: str
    album: str | None
    external_id: str | None


class TrackPage(BaseModel):
    items: list[TrackOut]
    total: int
    limit: int
    offset: int


class StatsOut(BaseModel):
    track: TrackOut
    first_recorded_at: datetime | None
    total_listened_ms: int
    event_count: int


class ChatInput(Input):
    question: str = Field(min_length=1, max_length=500)
    track_id: UUID | None = None


class ChatOut(BaseModel):
    status: Literal["answered", "needs_track", "ambiguous", "not_found", "unsupported"]
    answer: str
    metric: Literal["first", "total", "both"] | None = None
    track: TrackOut | None = None
    candidates: list[TrackOut] = Field(default_factory=list)
    first_recorded_at: datetime | None = None
    total_listened_ms: int | None = None

