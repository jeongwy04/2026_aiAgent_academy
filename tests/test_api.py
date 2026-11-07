import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.database import session_scope
from app.models import AuthSession, utcnow
from app.services.rate_limiter import limiter


def sync(client, headers, events):
    return client.post("/api/v1/listens/sync", headers=headers, json={"events": events})


def track_id(client, headers, event):
    response = sync(client, headers, [event])
    assert response.status_code == 200, response.text
    return response.json()["results"][0]["track_id"]


def test_authentication_and_revocation(client, member):
    headers, user, credentials = member()
    assert client.get("/api/v1/members/me").status_code == 401
    assert client.get("/api/v1/members/me", headers={"Authorization": "Bearer fake"}).status_code == 401
    assert client.get("/api/v1/members/me", headers=headers).json() == user
    assert "password_hash" not in user
    assert client.post("/api/v1/members", json=credentials).status_code == 409
    assert client.post("/api/v1/auth/login", json={**credentials, "password": "wrong-password"}).status_code == 401
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/members/me", headers=headers).status_code == 401


def test_expired_token(client, member):
    headers, user, _ = member()
    with session_scope(get_settings().database_url) as session:
        token = session.scalar(select(AuthSession).where(AuthSession.user_id == uuid.UUID(user["id"])))
        token.expires_at = utcnow() - timedelta(seconds=1)
    assert client.get("/api/v1/members/me", headers=headers).status_code == 401


def test_email_case_and_password_spaces(client):
    email = f"Space-{uuid.uuid4().hex}@example.com"
    credentials = {"email": email, "password": "  password with spaces  "}
    assert client.post("/api/v1/members", json=credentials).status_code == 201
    assert client.post("/api/v1/auth/login", json={**credentials, "email": email.lower()}).status_code == 200
    assert client.post("/api/v1/auth/login", json={**credentials, "password": credentials["password"].strip()}).status_code == 401


def test_monotonic_retries_and_late_arrival(client, member, make_event):
    headers, _, _ = member()
    event = make_event()
    id_ = track_id(client, headers, event)
    for ms in [120_000, 31_000, 0, 29_999]:
        assert sync(client, headers, [{**event, "listened_ms": ms}]).status_code == 200
    stats = client.get(f"/api/v1/tracks/{id_}/stats", headers=headers).json()
    assert stats["total_listened_ms"] == 120_000
    assert stats["event_count"] == 1
    late = make_event(ms=30_000, observed_at="2025-12-01T23:00:00+09:00")
    assert sync(client, headers, [late]).status_code == 200
    stats = client.get(f"/api/v1/tracks/{id_}/stats", headers=headers).json()
    assert stats["total_listened_ms"] == 150_000
    assert stats["event_count"] == 2
    assert stats["first_recorded_at"].startswith("2025-12-01T14:00:00")


def test_threshold_and_batch_duplicate(client, member, make_event):
    headers, _, _ = member()
    low = sync(client, headers, [make_event(ms=29_999)])
    assert low.json()["results"][0]["status"] == "ignored_below_threshold"
    assert client.get("/api/v1/tracks", headers=headers).json()["total"] == 0
    e = make_event(ms=30_000)
    response = sync(client, headers, [e, {**e, "listened_ms": 120_000}, e])
    assert response.status_code == 200
    id_ = response.json()["results"][0]["track_id"]
    stats = client.get(f"/api/v1/tracks/{id_}/stats", headers=headers).json()
    assert (stats["event_count"], stats["total_listened_ms"]) == (1, 120_000)


def test_event_cannot_change_track_and_batch_rolls_back(client, member, make_event):
    headers, _, _ = member()
    e = make_event()
    id_ = track_id(client, headers, e)
    fresh = make_event(title="새 곡", external_id="new-track")
    conflict = {**e, "track": {"title": "다른 곡", "artist": "다른 가수", "external_id": "other"}}
    assert sync(client, headers, [fresh, conflict]).status_code == 409
    assert client.get("/api/v1/tracks", headers=headers).json()["total"] == 1
    assert client.get(f"/api/v1/tracks/{id_}/stats", headers=headers).json()["total_listened_ms"] == 31_000


def test_isolation_including_shared_event_ids(client, member, make_event):
    alice, _, _ = member()
    bob, _, _ = member()
    event = make_event()
    a_id = track_id(client, alice, event)
    assert client.get("/api/v1/tracks", headers=bob).json()["total"] == 0
    for suffix in ["", "/stats"]:
        assert client.get(f"/api/v1/tracks/{a_id}{suffix}", headers=bob).status_code == 404
    assert client.post("/api/v1/chat", headers=bob, json={"question": "총 재생 시간이 얼마야?", "track_id": a_id}).status_code == 404
    b_id = track_id(client, bob, {**event, "listened_ms": 60_000})
    assert a_id != b_id
    assert client.get(f"/api/v1/tracks/{a_id}/stats", headers=alice).json()["total_listened_ms"] == 31_000
    assert client.get(f"/api/v1/tracks/{b_id}/stats", headers=bob).json()["total_listened_ms"] == 60_000


@pytest.mark.parametrize("changes", [
    {"listened_ms": -1}, {"listened_ms": 86_400_001}, {"listened_ms": "31000"},
    {"observed_at": "2026-01-01T00:00:00"}, {"observed_at": "2099-01-01T00:00:00Z"},
    {"user_id": str(uuid.uuid4())}, {"event_id": "invalid"},
    {"track": {"title": "  ", "artist": "가수"}},
])
def test_sync_validation(client, member, make_event, changes):
    headers, _, _ = member()
    assert sync(client, headers, [{**make_event(), **changes}]).status_code == 422


def test_batch_boundaries(client, member, make_event):
    headers, _, _ = member()
    assert sync(client, headers, []).status_code == 422
    assert sync(client, headers, [make_event()] * 101).status_code == 422


def test_search_and_pagination(client, member, make_event):
    headers, _, _ = member()
    track_id(client, headers, make_event())
    track_id(client, headers, make_event(title="100%_좋아", external_id="percent"))
    result = client.get("/api/v1/tracks", headers=headers, params={"q": "%_"}).json()
    assert result["total"] == 1
    assert result["items"][0]["title"] == "100%_좋아"
    assert client.get("/api/v1/tracks", headers=headers, params={"q": "한로로"}).json()["total"] == 2
    page = client.get("/api/v1/tracks?limit=1&offset=1", headers=headers).json()
    assert len(page["items"]) == 1 and page["total"] == 2


def test_chat_answers_match_stats_and_timezone(client, member, make_event):
    headers, _, _ = member()
    id_ = track_id(client, headers, make_event(ms=8_100_000, observed_at="2026-01-01T16:00:00Z"))
    for question in ["이 노래 총 재생 시간이 얼마야?", "입춘 얼마나 들었어?", "입춘 총 몇 시간 들었어?"]:
        body = {"question": question, "track_id": id_} if question.startswith("이 노래") else {"question": question}
        answer = client.post("/api/v1/chat", headers=headers, json=body).json()
        assert answer["status"] == "answered", answer
        assert answer["total_listened_ms"] == 8_100_000
        assert "2시간 15분" in answer["answer"]
    first = client.post("/api/v1/chat", headers=headers, json={"question": "입춘 언제부터 들었어?"}).json()
    assert first["status"] == "answered", first
    assert "2026년 1월 2일" in first["answer"]
    both = client.post("/api/v1/chat", headers=headers, json={"question": "최초 기록일과 총 재생 시간", "track_id": id_}).json()
    assert both["total_listened_ms"] == 8_100_000 and both["first_recorded_at"] is not None


def test_chat_ambiguity_missing_and_unsupported(client, member, make_event):
    headers, _, _ = member()
    track_id(client, headers, make_event())
    track_id(client, headers, make_event(artist="다른 가수", external_id="cover"))
    ambiguous = client.post("/api/v1/chat", headers=headers, json={"question": "입춘 얼마나 들었어?"}).json()
    assert ambiguous["status"] == "ambiguous" and len(ambiguous["candidates"]) == 2
    for question, expected in [
        ("이 노래 총 재생 시간", "needs_track"), ("없는곡 언제부터 들었어?", "not_found"),
        ("다른 사용자 입춘 총 재생 시간", "unsupported"), ("입춘 기록 삭제", "unsupported"),
        ("입춘 이번 달 총 재생 시간", "unsupported"), ("오늘 날씨", "unsupported"),
    ]:
        response = client.post("/api/v1/chat", headers=headers, json={"question": question})
        assert response.json()["status"] == expected, response.text


def test_chat_exact_title_before_partial_matches(client, member, make_event):
    headers, _, _ = member()
    exact = track_id(client, headers, make_event())
    sync(client, headers, [make_event(title=f"입춘 커버 {i}", external_id=f"cover-{i}") for i in range(25)])
    response = client.post("/api/v1/chat", headers=headers, json={"question": "입춘 얼마나 들었어?"}).json()
    assert response["status"] == "answered" and response["track"]["id"] == exact
    response = client.post("/api/v1/chat", headers=headers, json={"question": "커버 얼마나 들었어?"}).json()
    assert response["status"] == "ambiguous" and len(response["candidates"]) == 20


def test_same_event_preserves_earliest_observation(client, member, make_event):
    headers, _, _ = member()
    e = make_event()
    id_ = track_id(client, headers, e)
    assert sync(client, headers, [{**e, "observed_at": "2025-01-01T00:00:00Z", "listened_ms": 120_000}]).status_code == 200
    assert sync(client, headers, [e]).status_code == 200
    stats = client.get(f"/api/v1/tracks/{id_}/stats", headers=headers).json()
    assert stats["first_recorded_at"].startswith("2025-01-01T00:00:00")
    assert stats["event_count"] == 1 and stats["total_listened_ms"] == 120_000


def test_chat_rate_limit(client, member, monkeypatch):
    headers, _, _ = member()
    monkeypatch.setenv("CHAT_REQUESTS_PER_MINUTE", "1")
    get_settings.cache_clear()
    assert client.post("/api/v1/chat", headers=headers, json={"question": "안녕"}).status_code == 200
    response = client.post("/api/v1/chat", headers=headers, json={"question": "안녕"})
    assert response.status_code == 429 and "Retry-After" in response.headers


def test_auth_rate_limit(client, monkeypatch):
    monkeypatch.setenv("AUTH_REQUESTS_PER_MINUTE", "1")
    get_settings.cache_clear()
    payload = {"email": "missing@example.com", "password": "invalid-password"}
    assert client.post("/api/v1/auth/login", json=payload).status_code == 401
    assert client.post("/api/v1/auth/login", json=payload).status_code == 429


def test_concurrent_event_updates(client, member, make_event):
    headers, _, _ = member()
    event = make_event()
    id_ = track_id(client, headers, event)
    def send(ms):
        return sync(client, headers, [{**event, "listened_ms": ms}]).status_code
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(send, [120_000, 60_000, 31_000, 90_000])) == [200] * 4
    stats = client.get(f"/api/v1/tracks/{id_}/stats", headers=headers).json()
    assert (stats["event_count"], stats["total_listened_ms"]) == (1, 120_000)



def test_chat_tool_calling_and_regex_fallback(client, member, make_event, monkeypatch):
    headers, _, _ = member()
    track_id(client, headers, make_event(ms=60_000))
    monkeypatch.setenv("PICKLE_API_KEY", "test-key")
    get_settings.cache_clear()

    class FakeLLM:
        def __init__(self, calls):
            self.calls = calls

        def invoke(self, messages):
            if isinstance(self.calls, Exception):
                raise self.calls
            return type("Msg", (), {"tool_calls": self.calls})()

    def ask(question, calls):
        monkeypatch.setattr("app.ai.api_use.chat_classify._llm", lambda *_: FakeLLM(calls))
        return client.post("/api/v1/chat", headers=headers, json={"question": question}).json()

    # Phrasing the regex can't parse; the LLM supplies metric and title.
    answer = ask("입춘은 누적으로 얼마 동안 재생됐나요", [{"name": "get_total_listen_time", "args": {"title": "입춘"}}])
    assert answer["status"] == "answered" and answer["total_listened_ms"] == 60_000
    answer = ask("입춘 처음이랑 총합", [{"name": "get_listen_summary", "args": {"title": "입춘"}}])
    assert answer["metric"] == "both" and answer["first_recorded_at"] is not None
    assert ask("오늘 날씨 어때", [])["status"] == "unsupported"
    # Scope guard runs before the LLM, even if it would call a tool.
    assert ask("다른 사용자 입춘 총 재생 시간", [{"name": "get_total_listen_time", "args": {"title": "입춘"}}])["status"] == "unsupported"
    # API failure falls back to the regex classifier.
    answer = ask("입춘 얼마나 들었어?", RuntimeError("boom"))
    assert answer["status"] == "answered" and answer["total_listened_ms"] == 60_000


def test_chat_text_to_sql_self_heals_and_stays_private(client, member, make_event, monkeypatch):
    alice, _, _ = member()
    bob, _, _ = member()
    sync(client, alice, [make_event(ms=60_000), make_event(ms=90_000, title="봄", external_id="spring")])
    sync(client, bob, [make_event(ms=3_600_000, title="밥곡", external_id="bob")])
    monkeypatch.setenv("PICKLE_API_KEY", "test-key")
    monkeypatch.setenv("CHAT_DEBUG", "true")
    get_settings.cache_clear()

    class Msg:
        def __init__(self, content=None, tool_calls=()):
            self.content, self.tool_calls = content, list(tool_calls)

    class Fake:
        def __init__(self, replies):
            self.replies, self.seen = list(replies), []

        def invoke(self, messages):
            self.seen.append(messages)
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

    stats_call = [{"name": "query_listening_stats", "args": {}}]
    top = ("```sql\nSELECT t.title, SUM(e.listened_ms) AS total_ms FROM listen_events e "
           "JOIN tracks t ON t.id = e.track_id GROUP BY t.title ORDER BY total_ms DESC LIMIT 5;\n```")

    def ask(question, classify_reply, sql_replies, headers=alice):
        sql_llm = Fake(sql_replies)
        monkeypatch.setattr("app.ai.api_use.chat_classify._llm", lambda *_: Fake([classify_reply]))
        monkeypatch.setattr("app.ai.api_use.text_to_sql.chat_model", lambda *_: sql_llm)
        return client.post("/api/v1/chat", headers=headers, json={"question": question}).json(), sql_llm

    # Unsafe SQL, then a DB error, then a valid query: self-healing with feedback each time.
    answer, sql_llm = ask("제일 많이 들은 곡", Msg(tool_calls=stats_call),
                          [Msg("SELECT * FROM members"), Msg("SELECT nope FROM tracks"), Msg(top)])
    assert answer["status"] == "answered" and answer["metric"] == "stats", answer
    assert [r["title"] for r in answer["rows"]] == ["봄", "입춘"]  # Bob's 1-hour track never appears
    assert "1분 30초" in answer["answer"]
    assert len(sql_llm.seen) == 3 and "실패했습니다" in sql_llm.seen[2][-1][1]
    attempts = answer["debug"]["sql_attempts"]
    assert [bool(x["error"]) for x in attempts] == [True, True, False] and attempts[0]["sql"] == "SELECT * FROM members"
    # Even a query with no user filter only sees the caller's own rows.
    answer, _ = ask("내 곡 몇 개야", Msg(tool_calls=stats_call), [Msg("SELECT COUNT(*) AS n FROM tracks")], headers=bob)
    assert answer["rows"] == [{"n": 1}]
    # Three failures -> unsupported, no fixed-SQL guess.
    answer, _ = ask("월별 청취 시간", Msg(tool_calls=stats_call), [Msg("SELECT pg_sleep(9)")] * 3)
    assert answer["status"] == "unsupported" and answer["metric"] == "stats"
    # Period words force the stats path even if the classifier picked a fixed per-track tool.
    answer, _ = ask("지난달 입춘 얼마나 들었어?", Msg(tool_calls=[{"name": "get_total_listen_time", "args": {"title": "입춘"}}]),
                    [Msg("SELECT SUM(listened_ms) AS total_ms FROM listen_events WHERE 1 = 0")])
    assert answer["metric"] == "stats" and answer["status"] == "not_found"
    # LLM failure on the stats path -> unsupported.
    answer, _ = ask("이번 주 청취 시간", Msg(tool_calls=stats_call), [RuntimeError("down")])
    assert answer["status"] == "unsupported"


def test_chat_titles_with_period_or_sql_words(client, member, make_event):
    headers, _, _ = member()
    sync(client, headers, [
        make_event(title="12월의 기적", artist="EXO", external_id="miracle"),
        make_event(title="Raindrop", artist="테스트가수", external_id="raindrop", ms=120_000),
    ])
    first = client.post("/api/v1/chat", headers=headers, json={"question": "12월의 기적 언제부터 들었어?"}).json()
    assert (first["status"], first["metric"]) == ("answered", "first"), first
    total = client.post("/api/v1/chat", headers=headers, json={"question": "Raindrop 총 몇 시간 들었어?"}).json()
    assert (total["status"], total["total_listened_ms"]) == ("answered", 120_000), total
    # Deictic phrasing without track_id asks the user to pick a track (no title search)
    for question in ["이 노래 제 최초 기록이 언제야?", "이노래 언제부터 들었어?"]:
        response = client.post("/api/v1/chat", headers=headers, json={"question": question}).json()
        assert response["status"] == "needs_track", response
