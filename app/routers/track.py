from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.dependencies import CurrentMember, UserSession
from app.schemas import StatsOut, TrackOut, TrackPage
from app.services.track_service import owned_track, search_tracks, track_stats

router = APIRouter(prefix="/api/v1/tracks", tags=["track"])


@router.get("", response_model=TrackPage)
def tracks(user: CurrentMember, session: UserSession,
           q: Annotated[str, Query(max_length=300)] = "",
           limit: Annotated[int, Query(ge=1, le=100)] = 20,
           offset: Annotated[int, Query(ge=0, le=100_000)] = 0):
    return search_tracks(session, user.id, q, limit, offset)


@router.get("/{track_id}", response_model=TrackOut)
def track_detail(track_id: UUID, user: CurrentMember, session: UserSession):
    return owned_track(session, user.id, track_id)


@router.get("/{track_id}/stats", response_model=StatsOut)
def stats(track_id: UUID, user: CurrentMember, session: UserSession):
    return track_stats(session, user.id, owned_track(session, user.id, track_id))
