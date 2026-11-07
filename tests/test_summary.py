"""LLM 요약 가드레일: 근거 숫자만 허용, 실패하면 템플릿."""
from datetime import datetime

from app.ai.api_use.summary import facts, grounded, summarize
from app.config import get_settings

ROWS = [{"title": "입춘", "artist": "한로로", "total_ms": 7_380_000}]
TEMPLATE = "입춘 (한로로)입니다. (재생 시간 2시간 3분)"


class Fake:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def invoke(self, messages):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return type("Msg", (), {"content": self.reply})()


def use(monkeypatch, reply):
    fake = Fake(reply)
    def model(*args, **options):
        # The template already exists: the summary must not wait 10s x 2 like the other calls.
        assert options == {"timeout": 5, "max_retries": 0}
        return fake

    monkeypatch.setattr("app.ai.api_use.summary.chat_model", model)
    return fake


def test_facts_send_formatted_values_not_raw_numbers():
    text = facts(ROWS + [{"month": datetime(2026, 10, 1), "total_ms": 18_000_000}])
    assert "2시간 3분" in text and "2026년 10월" in text and "7380000" not in text


def test_grounded_numbers():
    data = facts(ROWS)
    assert grounded("이번 달엔 입춘을 2시간 3분 들었어요.", data, 1)
    assert not grounded("입춘을 3시간 들었어요.", data, 1)  # input has 3분, not 3시간
    assert not grounded("입춘을 2분 3시간 들었어요.", data, 1)
    assert not grounded("총 123분이에요.", data, 1)  # computed minutes are rejected
    two = "곡: A, 청취 횟수: 4회\n곡: B, 청취 횟수: 4회"
    assert grounded("1위는 A, 2번째는 B예요.", two, 2)  # ordinals for multi-row results
    assert not grounded("A를 2번 들었어요.", two, 2)  # "N번" reads as a count: rejected
    assert not grounded("A를 2회 들었어요.", two, 2)
    assert grounded("A를 4회 들었어요.", two, 2)
    for korean in ("세 곡을 들었어요.", "두 시간 들었어요.", "열네 번 들었어요.", "입춘을 한 번 들었어요."):
        assert not grounded(korean, data, 1), korean
    assert grounded("한로로의 입춘을 2시간 3분 들었어요.", data, 1)  # 한로로 is not a number word
    rows_3 = [{"title": "입춘", "play_count": 4}, {"title": "봄", "play_count": 2}, {"title": "밤", "play_count": 1}]
    assert not grounded("입춘을 2번 들었어요.", facts(rows_3), 3)  # 실제 4회 ("2번"은 순번으로 허용 안 함)
    assert not grounded("입춘을 3 들었어요.", facts(rows_3), 3)  # 단위 없는 순번 N도 허용 안 함
    assert not grounded("세 곡 들었어요.", "곡 수: 3개", 1)


def test_summarize_accepts_grounded_and_falls_back(monkeypatch):
    use(monkeypatch, "이번 달 가장 많이 들은 곡은 한로로의 입춘으로, 2시간 3분 들었어요.")
    answer, info = summarize("이번 달 가장 많이 들은 곡은?", ROWS, TEMPLATE)
    assert info["used"] and "입춘" in answer
    use(monkeypatch, "입춘을 약 2.1시간 들었어요.")  # rounded/computed number
    answer, info = summarize("이번 달 가장 많이 들은 곡은?", ROWS, TEMPLATE)
    assert answer == TEMPLATE and info["numbers_ok"] is False
    use(monkeypatch, RuntimeError("timeout"))
    assert summarize("q", ROWS, TEMPLATE) == (TEMPLATE, {"used": False, "numbers_ok": None, "candidate": None})
    use(monkeypatch, "가" * 301)
    assert summarize("q", ROWS, TEMPLATE)[0] == TEMPLATE


def test_chat_summary_flag(client, member, make_event, monkeypatch):
    from tests.test_api import sync
    headers, _, _ = member()
    sync(client, headers, [make_event(ms=60_000)])
    monkeypatch.setenv("PICKLE_API_KEY", "test-key")
    monkeypatch.setenv("CHAT_DEBUG", "true")
    get_settings.cache_clear()
    stats_call = type("Msg", (), {"tool_calls": [{"name": "query_listening_stats", "args": {}}]})()
    monkeypatch.setattr("app.ai.api_use.chat_classify._llm", lambda *_: type("L", (), {"invoke": lambda self, m: stats_call})())
    sql = type("Msg", (), {"content": "SELECT t.title, SUM(e.listened_ms) AS total_ms FROM listen_events e JOIN tracks t ON t.id = e.track_id GROUP BY t.title"})()
    monkeypatch.setattr("app.ai.api_use.text_to_sql.chat_model", lambda *_: type("L", (), {"invoke": lambda self, m: sql})())
    fake = use(monkeypatch, "가장 많이 들은 곡은 입춘이고 1분 들었어요.")

    off = client.post("/api/v1/chat", headers=headers, json={"question": "제일 많이 들은 곡"}).json()
    assert off["answer"] == "입춘입니다. (재생 시간 1분)" and fake.calls == 0  # default off: no LLM call
    monkeypatch.setenv("CHAT_LLM_SUMMARY", "true")
    get_settings.cache_clear()
    on = client.post("/api/v1/chat", headers=headers, json={"question": "제일 많이 들은 곡"}).json()
    assert on["answer"] == "가장 많이 들은 곡은 입춘이고 1분 들었어요." and on["debug"]["summary"]["used"]
    assert on["rows"] == off["rows"]  # raw rows unchanged for the app
    # Multi-row results always use the template (no LLM call)
    sync(client, headers, [make_event(ms=90_000, title="봄", external_id="spring")])
    calls = fake.calls
    many = client.post("/api/v1/chat", headers=headers, json={"question": "제일 많이 들은 곡"}).json()
    assert len(many["rows"]) == 2 and many["answer"].startswith("1. ") and fake.calls == calls
    assert "summary" not in many["debug"]
