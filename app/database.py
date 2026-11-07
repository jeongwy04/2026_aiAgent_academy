from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import get_settings


@lru_cache(maxsize=8)
def engine_for(url: str) -> Engine:
    options = {"check_same_thread": False} if url.startswith("sqlite") else {"connect_timeout": 5}
    return create_engine(url, pool_pre_ping=True, connect_args=options)


@contextmanager
def session_scope(url: str) -> Generator[Session, None, None]:
    with Session(engine_for(url), expire_on_commit=False) as session:
        with session.begin():
            yield session


def auth_session() -> Generator[Session, None, None]:
    with session_scope(get_settings().database_url) as session:
        yield session


def set_user_context(session: Session, user_id: str, *, readonly: bool = False) -> None:
    if session.bind.dialect.name == "postgresql":
        if readonly:
            session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(text("SELECT set_config('app.user_id', :id, true)"), {"id": user_id})
        session.execute(text("SELECT set_config('statement_timeout', :timeout, true)"),
                        {"timeout": str(get_settings().query_timeout_ms)})


def verify_database_roles() -> None:
    """Fail closed if either runtime account can bypass RLS or owns protected tables."""
    settings = get_settings()
    for url, readonly in [(settings.database_url, False), (settings.read_database_url, True)]:
        engine = engine_for(url)
        if engine.dialect.name != "postgresql":
            raise RuntimeError("운영 서버에는 PostgreSQL이 필요합니다.")
        with engine.connect() as connection:
            unsafe = connection.execute(text("""
                SELECT r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb
                       OR EXISTS (
                         SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                         WHERE n.nspname = 'public' AND c.relname IN ('tracks', 'listen_events', 'import_jobs', 'import_evidence', 'import_issues')
                         AND (pg_has_role(current_user, c.relowner, 'MEMBER')
                              OR NOT c.relrowsecurity OR NOT c.relforcerowsecurity))
                FROM pg_roles r WHERE r.rolname = current_user
            """)).scalar_one()
            count = connection.execute(text("""
                SELECT count(*) FROM pg_tables WHERE schemaname = 'public'
                AND tablename IN ('members', 'auth_sessions', 'tracks', 'listen_events', 'import_jobs', 'import_evidence', 'import_issues')
            """)).scalar_one()
            if unsafe or count != 7:
                raise RuntimeError("DB 역할 또는 마이그레이션이 안전하게 설정되지 않았습니다.")
            if readonly:
                can_write = connection.execute(text("""
                    SELECT bool_or(has_table_privilege(current_user, c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE'))
                    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind IN ('r','p')
                """)).scalar_one()
                if can_write:
                    raise RuntimeError("조회 전용 DB 역할에 쓰기 권한이 있습니다.")

