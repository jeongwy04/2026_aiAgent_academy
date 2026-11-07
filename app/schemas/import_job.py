from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ImportSummary(BaseModel):
    job_id: UUID
    status: Literal["completed"] = "completed"
    parser_version: str
    json_sha256: str
    total: int
    accepted: int
    inserted: int
    duplicates: int
    excluded: int
    review: int
    errors: int
    new_tracks: int
    distinct_tracks: int
    reasons: dict[str, dict[str, int]]


class ImportJobOut(BaseModel):
    job_id: UUID
    status: Literal["processing", "completed", "failed"]
    created_at: datetime
    completed_at: datetime | None
    result: ImportSummary | None
    error_code: str | None


class ImportIssueOut(BaseModel):
    source_index: int
    status: Literal["review", "error"]
    reason: str
    record: Any


class ImportIssuesPage(BaseModel):
    items: list[ImportIssueOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
