from fastapi import APIRouter
from sqlalchemy import text

from app.dependencies import AuthDB

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/ready")
def ready(session: AuthDB):
    session.execute(text("SELECT 1"))
    return {"status": "ready"}
