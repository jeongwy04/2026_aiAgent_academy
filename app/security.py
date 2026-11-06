import hashlib
import hmac
import secrets
from collections import OrderedDict
from datetime import timedelta, timezone
from threading import Lock
from time import monotonic
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import auth_session, session_scope, set_user_context
from app.models import AuthSession, Member, utcnow

bearer = HTTPBearer(auto_error=False)
PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def check_password(password: str, encoded: str) -> bool:
    _, rounds, salt, expected = encoded.split("$")
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
    return hmac.compare_digest(actual, expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(session: Session, user: Member) -> tuple[str, object]:
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(seconds=get_settings().token_ttl_seconds)
    session.add(AuthSession(token_hash=token_hash(token), user_id=user.id, expires_at=expires))
    session.flush()
    return token, expires


def unauthorized() -> HTTPException:
    return HTTPException(401, "로그인이 필요합니다.", headers={"WWW-Authenticate": "Bearer"})


def current_member(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(auth_session, scope="function")],
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


UserSession = Annotated[Session, Depends(user_session, scope="function")]
ReadSession = Annotated[Session, Depends(read_session, scope="function")]


class RateLimiter:
    """Per-process fixed windows, bounded memory. Shared limiter required for multiple workers."""
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = Lock()

    def check(self, key: str, limit: int):
        now = monotonic()
        with self.lock:
            while self.entries and next(iter(self.entries.values()))[0] + 60 <= now:
                self.entries.popitem(last=False)
            start, count = self.entries.get(key, (now, 0))
            if count >= limit:
                raise HTTPException(429, "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                                    headers={"Retry-After": str(max(1, int(60 - (now - start))))})
            if key not in self.entries and len(self.entries) >= 10_000:
                raise HTTPException(429, "서버가 혼잡합니다. 잠시 후 다시 시도해 주세요.", headers={"Retry-After": "60"})
            self.entries[key] = (start, count + 1)


limiter = RateLimiter()


def auth_limit(request: Request):
    # Do not trust spoofable forwarded headers. Configure trusted proxy at deployment.
    host = request.client.host if request.client else "unknown"
    limiter.check(f"auth:{host}", get_settings().auth_requests_per_minute)


def chat_limit(user: CurrentMember):
    limiter.check(f"chat:{user.id}", get_settings().chat_requests_per_minute)

