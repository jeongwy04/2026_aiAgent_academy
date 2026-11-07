from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.dependencies import AuthDB, CurrentMember, auth_limit, bearer
from app.models import AuthSession, Member
from app.schemas import Credentials, MemberOut, TokenOut
from app.services.auth import DUMMY_HASH, check_password, hash_password, issue_token, token_hash

router = APIRouter(prefix="/api/v1", tags=["member"])


@router.post("/members", response_model=MemberOut, status_code=201, dependencies=[Depends(auth_limit)])
def register(body: Credentials, session: AuthDB):
    user = Member(email=str(body.email).casefold(), password_hash=hash_password(body.password))
    session.add(user)
    try:
        session.flush()
    except IntegrityError as error:
        raise HTTPException(409, "이미 가입된 이메일입니다.") from error
    return user


@router.post("/auth/login", response_model=TokenOut, dependencies=[Depends(auth_limit)])
def login(body: Credentials, session: AuthDB):
    user = session.scalar(select(Member).where(Member.email == str(body.email).casefold()))
    valid = check_password(body.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not valid:
        raise HTTPException(401, "이메일 또는 비밀번호를 확인해 주세요.", headers={"WWW-Authenticate": "Bearer"})
    token, expires = issue_token(session, user)
    return TokenOut(access_token=token, expires_at=expires)


@router.post("/auth/logout", status_code=204)
def logout(user: CurrentMember, session: AuthDB, credentials=Depends(bearer)):
    session.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(credentials.credentials)))
    return Response(status_code=204)


@router.get("/members/me", response_model=MemberOut)
def me(user: CurrentMember):
    return user
