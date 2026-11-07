"""Read local secrets without printing them; touch only a new test database."""
import json
import os
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".test-results"
WORK.mkdir(exist_ok=True)
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
env = dotenv_values(ROOT / ".env")
admin_url = make_url(env["MIGRATION_DATABASE_URL"])
app_url = make_url(env["DATABASE_URL"])
read_url = make_url(env["READ_DATABASE_URL"])
admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
with admin.connect() as c:
    existing_database = c.scalar(sa.text("SELECT current_database()"))
    existing_tables = c.execute(sa.text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
    before = {name: c.scalar(sa.text(f'SELECT count(*) FROM "{name}"')) for name in existing_tables
              if name in {"members", "tracks", "listen_events", "import_jobs"}}
    print(json.dumps({"existing_database": existing_database, "connected": True,
                      "existing_tables": existing_tables, "existing_counts_before": before}))
    test_db = "firstlisten_import_test_" + uuid.uuid4().hex[:12]
    assert test_db.startswith("firstlisten_import_test_") and len(test_db) < 63
    c.exec_driver_sql(f'CREATE DATABASE "{test_db}"')

for key, url in (("MIGRATION_DATABASE_URL", admin_url), ("DATABASE_URL", app_url),
                 ("READ_DATABASE_URL", read_url), ("TEST_DATABASE_URL", app_url),
                 ("TEST_READ_DATABASE_URL", read_url)):
    os.environ[key] = url.set(database=test_db, host="127.0.0.1" if url.host == "localhost" else url.host).render_as_string(hide_password=False)
os.environ["PICKLE_API_KEY"] = ""
os.environ["IMPORT_REQUESTS_PER_MINUTE"] = "100"
os.environ["AUTH_REQUESTS_PER_MINUTE"] = "1000"
os.environ["CHAT_REQUESTS_PER_MINUTE"] = "1000"
(WORK / "db_test_context.json").write_text(json.dumps({"test_database": test_db, "existing_database": existing_database}), encoding="utf-8")
command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
print(json.dumps({"test_database": test_db, "migrated": True}))
exit_code = pytest.main(["-q", "--basetemp", str(WORK / ("pytest-pg-" + uuid.uuid4().hex[:8])), *sys.argv[1:]])
with admin.connect() as c:
    after = {name: c.scalar(sa.text(f'SELECT count(*) FROM "{name}"')) for name in before}
assert before == after, "Existing database row counts changed"
print(json.dumps({"pytest_exit_code": int(exit_code), "existing_counts_unchanged": before == after,
                  "test_database": test_db}))
raise SystemExit(int(exit_code))
