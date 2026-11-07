import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class ImportJob(Base):
    __tablename__ = "import_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_import_jobs_user_id"),
        CheckConstraint("status IN ('processing','completed','failed')", name="ck_import_job_status"),
        Index("ix_import_jobs_user_created", "user_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
    json_sha256: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImportEvidence(Base):
    __tablename__ = "import_evidence"
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "job_id"], ["import_jobs.user_id", "import_jobs.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["user_id", "event_id"], ["listen_events.user_id", "listen_events.event_id"], ondelete="CASCADE"),
        CheckConstraint("source_index >= 0", name="ck_import_evidence_index"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    raw_record: Mapped[dict] = mapped_column(JSON)


class ImportIssue(Base):
    __tablename__ = "import_issues"
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "job_id"], ["import_jobs.user_id", "import_jobs.id"], ondelete="CASCADE"),
        CheckConstraint("status IN ('review','error')", name="ck_import_issue_status"),
        CheckConstraint("source_index >= 0", name="ck_import_issue_index"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(80))
    raw_record: Mapped[dict | list | str | int | None] = mapped_column(JSON, nullable=True)
