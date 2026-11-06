import os
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.config import get_settings
from app.db import engine_for, set_user_context, session_scope, verify_database_roles

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql"), reason="PostgreSQL integration only")


def test_rls_direct_sql_and_pool_context(client, member, make_event):
    alice_headers, alice, _ = member()
    bob_headers, bob, _ = member()
    for headers in [alice_headers, bob_headers]:
        assert client.post("/api/v1/listens/sync", headers=headers, json={"events": [make_event()]}).status_code == 200
    verify_database_roles()
    engine = engine_for(get_settings().read_database_url)
    # Reuse the same physical connection to prove transaction-local state clears.
    with engine.connect() as connection:
        for user in [alice, bob, alice]:
            with connection.begin():
                connection.execute(text("SELECT set_config('app.user_id', :id, true)"), {"id": user["id"]})
                ids = connection.execute(text("SELECT DISTINCT user_id FROM listen_events")).scalars().all()
                assert ids == [UUID(user["id"])]
            with connection.begin():
                assert connection.execute(text("SELECT count(*) FROM listen_events")).scalar_one() == 0


def test_reader_cannot_write_or_read_auth(client):
    engine = engine_for(get_settings().read_database_url)
    for sql in ["DELETE FROM listen_events", "SELECT * FROM members", "SELECT * FROM auth_sessions"]:
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text(sql))


def test_app_cannot_forge_owner(client, member):
    _, alice, _ = member()
    _, bob, _ = member()
    with pytest.raises(DBAPIError):
        with session_scope(get_settings().database_url) as session:
            set_user_context(session, alice["id"])
            session.execute(text("""INSERT INTO tracks
                (id, user_id, source_key, title, artist, created_at)
                VALUES (gen_random_uuid(), :victim, 'forged', 'forged', 'forged', now())"""), {"victim": bob["id"]})


def test_query_timeout(client, member):
    _, user, _ = member()
    with pytest.raises(DBAPIError):
        with session_scope(get_settings().read_database_url) as session:
            set_user_context(session, user["id"], readonly=True)
            session.execute(text("SET LOCAL statement_timeout = '50ms'"))
            session.execute(text("SELECT pg_sleep(1)"))
