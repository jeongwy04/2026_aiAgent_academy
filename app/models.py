import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Member(Base):
    __tablename__ = "members"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


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
    artist: Mapped[str] = mapped_column(String(300))
    album: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ListenEvent(Base):
    __tablename__ = "listen_events"
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "track_id"], ["tracks.user_id", "tracks.id"], ondelete="CASCADE"),
        CheckConstraint("listened_ms >= 30000 AND listened_ms <= 86400000", name="ck_listen_duration"),
        Index("ix_events_user_track_observed", "user_id", "track_id", "observed_at"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    track_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    listened_ms: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

