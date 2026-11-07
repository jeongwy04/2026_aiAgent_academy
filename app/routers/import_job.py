import tempfile
import zipfile
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select

from app.config import get_settings
from app.dependencies import CurrentMember, ReadSession
from app.models import ImportIssue
from app.schemas.import_job import ImportIssueOut, ImportIssuesPage, ImportJobOut, ImportSummary
from app.services.import_service import import_takeout, owned_job
from app.services.rate_limiter import limiter

router = APIRouter(prefix="/api/v1/imports", tags=["import"])


def import_limit(user: CurrentMember):
    limiter.check(f"import:{user.id}", get_settings().import_requests_per_minute)


@router.post("", response_model=ImportSummary, dependencies=[Depends(import_limit)])
def upload_import(user: CurrentMember, file: Annotated[UploadFile, File()],
                  member: Annotated[str | None, Query(max_length=1000)] = None):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".zip", ".json"):
        raise HTTPException(422, "ZIP 또는 JSON 파일을 선택해 주세요.")
    # A synchronous MVP endpoint. Never issue 202 for an in-memory background task.
    try:
        with tempfile.TemporaryDirectory(prefix="firstlisten-upload-") as tmp:
            path = Path(tmp) / f"upload{suffix}"
            size = 0
            with path.open("wb") as target:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > get_settings().import_upload_max_bytes:
                        raise HTTPException(413, "업로드 크기 제한을 초과했습니다.")
                    target.write(chunk)
            return import_takeout(user.id, path, member=member,
                                   batch_size=get_settings().import_batch_size)
    except (ValueError, zipfile.BadZipFile, UnicodeError, RuntimeError) as error:
        # ImportStoreError must reach the dedicated 503 handler, not become 422.
        from app.services.import_service import ImportStoreError
        if isinstance(error, ImportStoreError):
            raise
        raise HTTPException(422, "가져오기 파일을 읽을 수 없습니다. JSON 형식·크기·ZIP 멤버를 확인해 주세요.") from None
    finally:
        file.file.close()


@router.get("/{job_id}", response_model=ImportJobOut)
def get_import(job_id: UUID, user: CurrentMember, session: ReadSession):
    job = owned_job(session, user.id, job_id)
    return ImportJobOut(job_id=job.id, status=job.status, created_at=job.created_at,
                        completed_at=job.completed_at, result=job.result, error_code=job.error_code)


@router.get("/{job_id}/issues", response_model=ImportIssuesPage)
def get_issues(job_id: UUID, user: CurrentMember, session: ReadSession,
               limit: Annotated[int, Query(ge=1, le=100)] = 20,
               offset: Annotated[int, Query(ge=0)] = 0):
    owned_job(session, user.id, job_id)
    query = select(ImportIssue).where(ImportIssue.user_id == user.id, ImportIssue.job_id == job_id)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    issues = session.scalars(query.order_by(ImportIssue.source_index).limit(limit).offset(offset))
    return ImportIssuesPage(items=[ImportIssueOut(source_index=i.source_index, status=i.status,
        reason=i.reason, record=i.raw_record) for i in issues], total=total, limit=limit, offset=offset)
