"""비밀번호 해시(PBKDF2)와 토큰 발급. 토큰은 SHA-256 해시로만 저장합니다."""
import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuthSession, Member, utcnow

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


# Equal-cost hash for unknown accounts to avoid a cheap email timing oracle.
DUMMY_HASH = hash_password("dummy-password-not-an-account")
