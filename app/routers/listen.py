from fastapi import APIRouter

from app.dependencies import CurrentMember, UserSession
from app.schemas import SyncInput, SyncOut
from app.services.listen_service import sync_events

router = APIRouter(prefix="/api/v1/listens", tags=["listen"])


@router.post("/sync", response_model=SyncOut)
def sync(body: SyncInput, user: CurrentMember, session: UserSession):
    return sync_events(session, user.id, body.events)
