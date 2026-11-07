"""본인 곡 검색·상세·통계."""
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ListenEvent, Track
from app.schemas import StatsOut, TrackOut, TrackPage


def search_tracks(session: Session, user_id: uuid.UUID, q: str, limit: int, offset: int) -> TrackPage:
    query = select(Track).where(Track.user_id == user_id)
    if q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Track.title.ilike(f"%{escaped}%", escape="\\") | Track.artist.ilike(f"%{escaped}%", escape="\\"))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    items = session.scalars(query.order_by(Track.title, Track.artist, Track.id).offset(offset).limit(limit))
    return TrackPage(items=[TrackOut.model_validate(t) for t in items], total=total, limit=limit, offset=offset)


def owned_track(session: Session, user_id: uuid.UUID, track_id: uuid.UUID) -> Track:
    track = session.scalar(select(Track).where(Track.id == track_id, Track.user_id == user_id))
    if track is None:
        raise HTTPException(404, "해당 곡의 청취 기록이 없습니다.")
    return track


def track_stats(session: Session, user_id: uuid.UUID, track: Track) -> StatsOut:
    first, total, count = session.execute(select(
        func.min(ListenEvent.observed_at), func.coalesce(func.sum(ListenEvent.listened_ms), 0), func.count()
    ).where(ListenEvent.user_id == user_id, ListenEvent.track_id == track.id)).one()
    return StatsOut(track=TrackOut.model_validate(track), first_recorded_at=first,
                    total_listened_ms=int(total), event_count=count)
