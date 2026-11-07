"""라우터에서 Depends로 주입하는 공통 의존성: DB 세션, 로그인 회원, 요청 제한."""
from datetime import timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import auth_session, session_scope, set_user_context
from app.models import AuthSession, Member, utcnow
from app.services.auth import token_hash
from app.services.rate_limiter import limiter

bearer = HTTPBearer(auto_error=False)

# 인증 전용 세션 (회원·토큰 테이블)
AuthDB = Annotated[Session, Depends(auth_session, scope="function")]


def unauthorized() -> HTTPException:
    return HTTPException(401, "로그인이 필요합니다.", headers={"WWW-Authenticate": "Bearer"})


def current_member(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: AuthDB,
) -> Member:
    if credentials is None or len(credentials.credentials) > 256:
        raise unauthorized()
    stored = session.get(AuthSession, token_hash(credentials.credentials))
    if stored is None:
        raise unauthorized()
    expires = stored.expires_at.replace(tzinfo=timezone.utc) if stored.expires_at.tzinfo is None else stored.expires_at
    if expires <= utcnow():
        raise unauthorized()
    user = session.get(Member, stored.user_id)
    if user is None:
        raise unauthorized()
    return user


CurrentMember = Annotated[Member, Depends(current_member)]


def user_session(user: CurrentMember):
    with session_scope(get_settings().database_url) as session:
        set_user_context(session, str(user.id))
        yield session


def read_session(user: CurrentMember):
    with session_scope(get_settings().read_database_url) as session:
        set_user_context(session, str(user.id), readonly=True)
        yield session


# RLS 사용자 컨텍스트가 걸린 세션 (쓰기 / 읽기 전용)
UserSession = Annotated[Session, Depends(user_session, scope="function")]
ReadSession = Annotated[Session, Depends(read_session, scope="function")]


def auth_limit(request: Request):
    # Do not trust spoofable forwarded headers. Configure trusted proxy at deployment.
    host = request.client.host if request.client else "unknown"
    limiter.check(f"auth:{host}", get_settings().auth_requests_per_minute)


def chat_limit(user: CurrentMember):
    limiter.check(f"chat:{user.id}", get_settings().chat_requests_per_minute)
