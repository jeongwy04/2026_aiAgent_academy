import os
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.config import get_settings
from app.database import engine_for, set_user_context, session_scope, verify_database_roles

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


def test_import_tables_force_rls_and_reader_cannot_write(client, member):
    import json
    alice_headers, alice, _ = member()
    _, bob, _ = member()
    rows = [{"header": "YouTube Music", "title": "샘플 을(를) 시청했습니다.",
             "titleUrl": "https://music.youtube.com/watch?v=abcdefghijk", "time": "2025-01-01T00:00:00Z"},
            {"header": "YouTube Music", "title": "unrecognized", "time": "2025-01-01T00:00:00Z"}]
    response = client.post("/api/v1/imports", headers=alice_headers,
        files={"file": ("history.json", json.dumps(rows).encode(), "application/json")})
    assert response.status_code == 200, response.text
    engine = engine_for(get_settings().read_database_url)
    for table in ("import_jobs", "import_evidence", "import_issues"):
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text("SELECT set_config('app.user_id', :id, true)"), {"id": alice["id"]})
                assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() >= 1
            for user in (bob, None):
                with connection.begin():
                    if user:
                        connection.execute(text("SELECT set_config('app.user_id', :id, true)"), {"id": user["id"]})
                    assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text(f"DELETE FROM {table}"))
    with pytest.raises(DBAPIError):
        with session_scope(get_settings().database_url) as session:
            set_user_context(session, alice["id"])
            session.execute(text("""INSERT INTO import_jobs
                (id,user_id,json_sha256,parser_version,status,created_at)
                VALUES (gen_random_uuid(),:victim,repeat('a',64),'1.0.0','processing',now())"""), {"victim": bob["id"]})


def test_concurrent_import_lock_rejects_and_recovers(client, member):
    import hashlib
    import json
    headers, user, _ = member()
    lock_key = int.from_bytes(hashlib.sha256(UUID(user["id"]).bytes).digest()[:8], "big", signed=True)
    with session_scope(get_settings().database_url) as session:
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        response = client.post("/api/v1/imports", headers=headers,
            files={"file": ("history.json", json.dumps([]).encode(), "application/json")})
        assert response.status_code == 409
    response = client.post("/api/v1/imports", headers=headers,
        files={"file": ("history.json", b"[]", "application/json")})
    assert response.status_code == 200
