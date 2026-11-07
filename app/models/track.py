import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (
        UniqueConstraint("user_id", "source_key", name="uq_tracks_user_source"),
        UniqueConstraint("user_id", "id", name="uq_tracks_user_id"),
        Index("ix_tracks_user_title", "user_id", "title"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
    source_key: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    artist: Mapped[str | None] = mapped_column(String(300), nullable=True)
    album: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ListenEvent(Base):
    __tablename__ = "listen_events"
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "track_id"], ["tracks.user_id", "tracks.id"], ondelete="CASCADE"),
        CheckConstraint("(source = 'android_media_session' AND listened_ms IS NOT NULL AND listened_ms >= 30000 AND listened_ms <= 86400000) OR (source = 'google_takeout_my_activity' AND listened_ms IS NULL AND source_event_key IS NOT NULL)", name="ck_listen_source_duration"),
        CheckConstraint("occurrence_no >= 1", name="ck_listen_occurrence"),
        UniqueConstraint("user_id", "source", "source_event_key", "occurrence_no", name="uq_events_source_occurrence"),
        Index("ix_events_user_track_observed", "user_id", "track_id", "observed_at"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    track_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    listened_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="android_media_session", server_default="android_media_session")
    source_event_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurrence_no: Mapped[int] = mapped_column(default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
