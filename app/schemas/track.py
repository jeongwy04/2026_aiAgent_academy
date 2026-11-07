from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TrackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    artist: str | None
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
    total_listened_ms: int | None
    event_count: int
    measured_event_count: int = 0
    unknown_duration_event_count: int = 0
