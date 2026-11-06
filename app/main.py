from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.chat import answer_question
from app.db import auth_session, engine_for, verify_database_roles
from app.config import get_settings
from app.listening import owned_track, sync_events, track_stats
from app.models import AuthSession, Member, Track
from app.schemas import ChatInput, ChatOut, Credentials, MemberOut, StatsOut, SyncInput, SyncOut, TokenOut, TrackOut, TrackPage
from app.security import CurrentMember, ReadSession, UserSession, auth_limit, bearer, chat_limit, check_password, hash_password, issue_token, token_hash


@asynccontextmanager
async def lifespan(app: FastAPI):
    verify_database_roles()
    yield
    for url in {get_settings().database_url, get_settings().read_database_url}:
        engine_for(url).dispose()


app = FastAPI(title="FirstListen API", version="0.1.0", lifespan=lifespan)
AuthDB = Annotated[Session, Depends(auth_session, scope="function")]
# Equal-cost hash for unknown accounts to avoid a cheap email timing oracle.
DUMMY_HASH = hash_password("dummy-password-not-an-account")


@app.exception_handler(OperationalError)
async def database_error(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={"detail": "데이터베이스 요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."})


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
def ready(session: AuthDB):
    session.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.post("/api/v1/members", response_model=MemberOut, status_code=201, tags=["member"], dependencies=[Depends(auth_limit)])
def register(body: Credentials, session: AuthDB):
    user = Member(email=str(body.email).casefold(), password_hash=hash_password(body.password))
    session.add(user)
    try:
        session.flush()
    except IntegrityError as error:
        raise HTTPException(409, "이미 가입된 이메일입니다.") from error
    return user


@app.post("/api/v1/auth/login", response_model=TokenOut, tags=["member"], dependencies=[Depends(auth_limit)])
def login(body: Credentials, session: AuthDB):
    user = session.scalar(select(Member).where(Member.email == str(body.email).casefold()))
    valid = check_password(body.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not valid:
        raise HTTPException(401, "이메일 또는 비밀번호를 확인해 주세요.", headers={"WWW-Authenticate": "Bearer"})
    token, expires = issue_token(session, user)
    return TokenOut(access_token=token, expires_at=expires)


@app.post("/api/v1/auth/logout", status_code=204, tags=["member"])
def logout(user: CurrentMember, session: AuthDB, credentials=Depends(bearer)):
    session.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(credentials.credentials)))
    return Response(status_code=204)


@app.get("/api/v1/members/me", response_model=MemberOut, tags=["member"])
def me(user: CurrentMember):
    return user


@app.post("/api/v1/listens/sync", response_model=SyncOut, tags=["listen"])
def sync(body: SyncInput, user: CurrentMember, session: UserSession):
    return sync_events(session, user.id, body.events)


@app.get("/api/v1/tracks", response_model=TrackPage, tags=["track"])
def tracks(user: CurrentMember, session: UserSession,
           q: Annotated[str, Query(max_length=300)] = "",
           limit: Annotated[int, Query(ge=1, le=100)] = 20,
           offset: Annotated[int, Query(ge=0, le=100_000)] = 0):
    query = select(Track).where(Track.user_id == user.id)
    if q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Track.title.ilike(f"%{escaped}%", escape="\\") | Track.artist.ilike(f"%{escaped}%", escape="\\"))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    items = session.scalars(query.order_by(Track.title, Track.artist, Track.id).offset(offset).limit(limit))
    return TrackPage(items=[TrackOut.model_validate(t) for t in items], total=total, limit=limit, offset=offset)


@app.get("/api/v1/tracks/{track_id}", response_model=TrackOut, tags=["track"])
def track_detail(track_id: UUID, user: CurrentMember, session: UserSession):
    return owned_track(session, user.id, track_id)


@app.get("/api/v1/tracks/{track_id}/stats", response_model=StatsOut, tags=["track"])
def stats(track_id: UUID, user: CurrentMember, session: UserSession):
    return track_stats(session, user.id, owned_track(session, user.id, track_id))


@app.post("/api/v1/chat", response_model=ChatOut, tags=["chat"], dependencies=[Depends(chat_limit)])
def chat(body: ChatInput, user: CurrentMember, session: ReadSession):
    return answer_question(session, user.id, body)
