import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import engine_for
from app.main import app
from app.models import Base
from app.services.rate_limiter import limiter


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    read_url = os.getenv("TEST_READ_DATABASE_URL", url)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("READ_DATABASE_URL", read_url)
    monkeypatch.setenv("AUTH_REQUESTS_PER_MINUTE", "1000")
    monkeypatch.setenv("CHAT_REQUESTS_PER_MINUTE", "1000")
    monkeypatch.setenv("PICKLE_API_KEY", "")  # regex classifier; LLM path is mocked per test
    get_settings.cache_clear()
    limiter.entries.clear()
    if url.startswith("sqlite"):
        Base.metadata.create_all(engine_for(url))
        monkeypatch.setattr("app.main.verify_database_roles", lambda: None)
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture
def member(client):
    def create():
        email = f"test-{uuid.uuid4().hex}@example.com"
        credentials = {"email": email, "password": "safe-test-password!"}
        response = client.post("/api/v1/members", json=credentials)
        assert response.status_code == 201, response.text
        user = response.json()
        response = client.post("/api/v1/auth/login", json=credentials)
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}, user, credentials
    return create


def event(*, event_id=None, ms=31_000, title="입춘", artist="한로로", external_id="ipchun", observed_at="2026-01-02T01:00:00Z"):
    return {
        "event_id": str(event_id or uuid.uuid4()),
        "track": {"title": title, "artist": artist, "external_id": external_id},
        "observed_at": observed_at, "listened_ms": ms,
    }


@pytest.fixture
def make_event():
    return event

