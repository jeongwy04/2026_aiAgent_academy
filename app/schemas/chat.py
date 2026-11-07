from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import Input
from app.schemas.track import TrackOut


class ChatInput(Input):
    question: str = Field(min_length=1, max_length=500)
    track_id: UUID | None = None


class ChatOut(BaseModel):
    question: str
    answer: str
    status: Literal["answered", "needs_track", "ambiguous", "not_found", "unsupported"]
    metric: Literal["first", "total", "both", "stats"] | None = None
    track: TrackOut | None = None
    candidates: list[TrackOut] = Field(default_factory=list)
    first_recorded_at: datetime | None = None
    total_listened_ms: int | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)  # stats(Text-to-SQL) 결과, 최대 50행
    debug: dict[str, Any] | None = None  # CHAT_DEBUG=true일 때만: {"sql_attempts": [...]}
