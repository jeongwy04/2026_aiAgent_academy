"""청취 이벤트 동기화: 곡 upsert + 이벤트 upsert (재시도·지연 도착에도 중복 합산 없음)."""
import hashlib
import json
import uuid

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import ListenEvent, Track, utcnow
from app.schemas import EventInput, EventResult, SyncOut, TrackInput
from app.utils import normalized

MIN_LISTENED_MS = 30_000


def source_key(track: TrackInput) -> str:
    # External IDs remain case-sensitive. Metadata fallback cannot distinguish
    # recordings with identical title/artist/album; prefer an external ID.
    identity = ["youtube_music", "id", track.external_id] if track.external_id else [
        "youtube_music", "metadata", normalized(track.title), normalized(track.artist), normalized(track.album)
    ]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def insert_for(session: Session, model):
    if session.bind.dialect.name == "postgresql":
        return pg_insert(model)
    if session.bind.dialect.name == "sqlite":
        return sqlite_insert(model)
    raise RuntimeError("Unsupported database")


def save_event(session: Session, user_id: uuid.UUID, event: EventInput) -> EventResult:
    if event.listened_ms < MIN_LISTENED_MS:
        return EventResult(event_id=event.event_id, status="ignored_below_threshold")
    track_id = uuid.uuid4()
    track_insert = insert_for(session, Track).values(
        id=track_id, user_id=user_id, source_key=source_key(event.track),
        **event.track.model_dump(), created_at=utcnow(),
    )
    # ON CONFLICT is atomic even when two device syncs discover the same track.
    track_id = session.execute(track_insert.on_conflict_do_update(
        index_elements=[Track.user_id, Track.source_key],
        set_={"source_key": track_insert.excluded.source_key},
    ).returning(Track.id)).scalar_one()

    event_insert = insert_for(session, ListenEvent).values(
        user_id=user_id, event_id=event.event_id, track_id=track_id,
        observed_at=event.observed_at, listened_ms=event.listened_ms, updated_at=utcnow(),
    )
    greatest = func.greatest if session.bind.dialect.name == "postgresql" else func.max
    least = func.least if session.bind.dialect.name == "postgresql" else func.min
    stored = session.execute(event_insert.on_conflict_do_update(
        index_elements=[ListenEvent.user_id, ListenEvent.event_id],
        set_={
            "listened_ms": greatest(ListenEvent.listened_ms, event_insert.excluded.listened_ms),
            "observed_at": least(ListenEvent.observed_at, event_insert.excluded.observed_at),
            "updated_at": utcnow(),
        },
        where=ListenEvent.track_id == track_id,
    ).returning(ListenEvent.listened_ms)).scalar_one_or_none()
    if stored is None:
        raise HTTPException(409, "같은 event_id를 다른 곡에 재사용할 수 없습니다. 배치 전체가 취소되었습니다.")
    return EventResult(event_id=event.event_id, status="accepted", track_id=track_id, listened_ms=stored)


def sync_events(session: Session, user_id: uuid.UUID, events: list[EventInput]) -> SyncOut:
    return SyncOut(results=[save_event(session, user_id, event) for event in events])
