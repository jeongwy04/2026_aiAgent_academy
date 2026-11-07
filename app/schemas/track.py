from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
