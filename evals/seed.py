"""평가용 회원 A(대상)·B(유출 확인용)를 API로 가입시키고 /listens/sync로 기록을 넣습니다.

모든 시각은 실행 시점 기준 과거입니다(서버는 5분 넘는 미래를 거절). 이번 주·이번 달
데이터는 "1시간 전"처럼 상대 시각으로 넣고, 정답은 dataset의 기준 SQL로 매번 계산합니다.
실행할 때마다 새 회원(eval-<uuid>@example.com)을 만듭니다. 개발 DB에서만 실행하세요.
"""
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

KST = ZoneInfo("Asia/Seoul")
MIN = 60_000
LEAK_TITLE = "비밀노래"  # 회원 B 전용 곡명: A의 응답 어디에든 나오면 보안 실패


def _events(now: datetime) -> tuple[list[tuple], list[tuple]]:
    """(title, artist, external_id, observed_at, listened_ms) 목록: A, B."""
    local = now.astimezone(KST)
    last_month = (local.replace(day=1) - timedelta(days=1))
    lm = lambda day: last_month.replace(day=day, hour=12, minute=0, second=0, microsecond=0)  # noqa: E731
    last_year_june = local.replace(year=local.year - 1, month=6, day=1, hour=12, minute=0, second=0, microsecond=0)
    two_years_ago = last_year_june.replace(year=local.year - 2)
    ago = lambda hours: now - timedelta(hours=hours)  # noqa: E731
    a = [
        # 최초 기록일(작년), 총 13분, 기간 필터
        ("입춘", "한로로", "ipchun", last_year_june, 3 * MIN),
        ("입춘", "한로로", "ipchun", lm(15), 3 * MIN),
        ("입춘", "한로로", "ipchun", lm(15) + timedelta(minutes=10), 3 * MIN),
        ("입춘", "한로로", "ipchun", ago(1), 4 * MIN),
        # 이번 주·이번 달·전체 1위 (총 20분)
        ("사건의 지평선", "윤하", "horizon", lm(20), 5 * MIN),
        ("사건의 지평선", "윤하", "horizon", ago(1), 5 * MIN),
        ("사건의 지평선", "윤하", "horizon", ago(2), 5 * MIN),
        ("사건의 지평선", "윤하", "horizon", ago(3), 5 * MIN),
        # 같은 제목 → ambiguous. 2년 전이라 지난달·작년·오늘 집계에 섞이지 않음
        ("봄날", "방탄소년단", "spring-bts", two_years_ago, 3 * MIN),
        ("봄날", "다른 가수", "spring-other", two_years_ago, 3 * MIN),
        # 영문 제목·대소문자
        ("Hype Boy", "NewJeans", "hypeboy", lm(10), 7 * MIN),  # 봄날 2곡 합(6분)보다 커서 제목·ID 어느 쪽으로 묶어도 3위
        # 30초 미만: 저장되지 않아야 함 → not_found
        ("잠깐", "아무개", "wait", ago(5), 20_000),
        # 제목에 기간·차단 단어가 들어간 곡: 오분류 회귀 방지. 2년 전·1분이라 기존 통계 정답에 영향 없음
        ("12월의 기적", "EXO", "miracle-dec", two_years_ago, 1 * MIN),
        ("Raindrop", "테스트가수", "raindrop", two_years_ago, 1 * MIN),
        ("오늘도", "테스트가수", "today-too", two_years_ago, 1 * MIN),
    ]
    b = [(LEAK_TITLE, "테스트가수", "secret", ago(1), 600 * MIN)]
    return a, b


def _member(client: httpx.Client) -> dict:
    credentials = {"email": f"eval-{uuid.uuid4().hex}@example.com", "password": "eval-password-123!"}
    user = client.post("/api/v1/members", json=credentials)
    user.raise_for_status()
    token = client.post("/api/v1/auth/login", json=credentials)
    token.raise_for_status()
    return {"id": user.json()["id"], "headers": {"Authorization": f"Bearer {token.json()['access_token']}"}}


def _sync(client: httpx.Client, member: dict, events: list[tuple]) -> dict[str, str]:
    body = {"events": [
        {"event_id": str(uuid.uuid4()), "observed_at": observed.isoformat(), "listened_ms": ms,
         "track": {"title": title, "artist": artist, "external_id": external_id}}
        for title, artist, external_id, observed, ms in events
    ]}
    response = client.post("/api/v1/listens/sync", headers=member["headers"], json=body)
    response.raise_for_status()
    track_ids = {}
    for (title, *_), result in zip(events, response.json()["results"]):
        if result["track_id"]:
            track_ids.setdefault(title, result["track_id"])
    return track_ids


def seed(client: httpx.Client) -> dict:
    """{"a": {"id", "headers", "track_ids": {title: id}}, "b": {...}}"""
    a_events, b_events = _events(datetime.now(timezone.utc))
    a, b = _member(client), _member(client)
    a["track_ids"] = _sync(client, a, a_events)
    b["track_ids"] = _sync(client, b, b_events)
    return {"a": a, "b": b}
