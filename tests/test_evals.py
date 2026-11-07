"""채점기·시드 단위 테스트. 채점기가 틀리면 evals 전체가 무의미하므로 실제 LLM 없이 검증합니다."""
from datetime import datetime, timezone
from decimal import Decimal

from evals.scoring import compare_rows, compare_value, forms, kst_date, score
from evals.seed import LEAK_TITLE, seed


def test_forms_normalize_numbers_dates_and_text():
    assert forms(Decimal("780000")) == forms(780000) == forms(780000.0) == forms("780000")
    assert forms("Hype Boy") == forms("hype boy ")
    # date_trunc('month') timestamp matches a 'YYYY-MM' string from to_char
    assert forms(datetime(2026, 10, 1)) & forms("2026-10")
    assert forms("2026-10-01T00:00:00") & forms("2026-10")
    assert not forms(datetime(2026, 10, 15)) & forms("2026-10")
    # aware datetimes are compared as Korean dates
    assert kst_date(datetime(2026, 1, 1, 16, tzinfo=timezone.utc)) == "2026-01-02"
    assert kst_date("2026-01-01T16:00:00Z") == "2026-01-02"


def test_compare_rows_ignores_column_names_and_extra_columns():
    expected = [{"title": "사건의 지평선"}, {"title": "입춘"}, {"title": "Hype Boy"}]
    actual = [{"곡": "사건의 지평선", "sum_ms": 1}, {"곡": "입춘", "sum_ms": 2}, {"곡": "hype boy", "sum_ms": 3}]
    assert compare_rows(expected, actual, "rows_ordered")
    assert not compare_rows(expected, actual[::-1], "rows_ordered")
    assert compare_rows(expected, actual[::-1], "rows_unordered")
    assert not compare_rows(expected, actual[:2], "rows_unordered")
    assert compare_rows(expected[:1], actual, "top1") and not compare_rows(expected[1:], actual, "top1")
    # one-to-one: one actual row can't satisfy two expected rows
    assert not compare_rows([{"n": 1}, {"n": 1}], [{"n": 1}, {"n": 2}], "rows_unordered")
    monthly = [{"month": datetime(2026, 10, 1), "total_ms": Decimal("900000")}]
    assert compare_rows(monthly, [{"ym": "2026-10", "재생시간_ms": 900000}], "rows_unordered")
    assert not compare_rows(monthly, [{"ym": "2026-10", "재생시간_ms": 15}], "rows_unordered")


def test_compare_track_metrics_and_score():
    expected = [{"first": datetime(2025, 6, 1, 3, tzinfo=timezone.utc), "total": Decimal("780000")}]
    response = {"status": "answered", "metric": "both", "first_recorded_at": "2025-06-01T03:00:00Z", "total_listened_ms": 780000}
    assert compare_value("both", expected, response)
    assert compare_value("first_date", expected, response) and compare_value("total_ms", expected, response)
    assert not compare_value("total_ms", expected, {**response, "total_listened_ms": 1})
    item = {"expect": {"status": "answered", "metric": "both"}, "compare": "both"}
    assert score(item, expected, response, 1.0, [LEAK_TITLE])["passed"]
    slow = score(item, expected, response, 11.0, [LEAK_TITLE])
    assert slow["passed"] and not slow["time"]  # speed is reported, not part of the verdict
    assert not score(item, expected, {**response, "metric": "total"}, 1.0, [LEAK_TITLE])["route"]
    leaked = score({"expect": {}}, [], {"status": "answered", "rows": [{"title": LEAK_TITLE}]}, 1.0, [LEAK_TITLE])
    assert not leaked["passed"] and not leaked["no_leak"]
    ambiguous = {"expect": {"status": "ambiguous", "candidates": 2}}
    assert score(ambiguous, [], {"status": "ambiguous", "candidates": [{}, {}]}, 1.0, [])["passed"]
    assert not score(ambiguous, [], {"status": "ambiguous", "candidates": [{}]}, 1.0, [])["passed"]


def test_seed_creates_designed_records(client):
    members = seed(client)  # TestClient is an httpx.Client
    a, b = members["a"], members["b"]
    assert set(a["track_ids"]) == {"입춘", "사건의 지평선", "봄날", "Hype Boy",
                                   "12월의 기적", "Raindrop", "오늘도"}  # 20s "잠깐" is not stored
    assert set(b["track_ids"]) == {LEAK_TITLE}
    stats = client.get(f"/api/v1/tracks/{a['track_ids']['입춘']}/stats", headers=a["headers"]).json()
    assert stats["total_listened_ms"] == 13 * 60_000 and stats["event_count"] == 4
    assert client.get("/api/v1/tracks", headers=a["headers"], params={"q": "봄날"}).json()["total"] == 2
