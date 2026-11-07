"""프로젝트 진입점: 앱 객체 생성, 시작 시 DB 권한 점검, 라우터 등록."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.database import engine_for, verify_database_roles
from app.routers import chat, listen, member, system, track, import_job
from app.services.import_service import ImportStoreError


@asynccontextmanager
async def lifespan(app: FastAPI):
    verify_database_roles()
    yield
    for url in {get_settings().database_url, get_settings().read_database_url}:
        engine_for(url).dispose()


app = FastAPI(title="FirstListen API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(OperationalError)
async def database_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": "데이터베이스 요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."})


app.include_router(system.router)
app.include_router(member.router)
app.include_router(listen.router)
app.include_router(track.router)
app.include_router(chat.router)
app.include_router(import_job.router)


@app.exception_handler(ImportStoreError)
async def import_storage_error(request, exc):
    return JSONResponse(status_code=503, content={
        "detail": "가져오기 저장 완료를 확인하지 못했습니다. 같은 파일로 다시 시도해 주세요.",
        "job_id": str(exc.job_id),
    })
