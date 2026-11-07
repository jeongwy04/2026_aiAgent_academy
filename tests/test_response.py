"""Text-to-SQL 결과 → 한국어 문장 (결과 모양별 문장 틀)."""
from datetime import date, datetime, timezone
from decimal import Decimal

from app.ai.api_use.query.response import format_rows, label, value


def test_single_value():
    assert format_rows([{"track_count": 3}], "지난달에 들은 곡 몇 개야?") == "3곡입니다."
    assert format_rows([{"n": 7}], "오늘 몇 개 들었어?") == "개수: 7개입니다."
    assert format_rows([{"play_count": 14}], "오늘 몇 곡 들었어?") == "청취 횟수: 14회입니다."  # 재생 횟수는 '곡'으로 바꾸지 않음
    assert format_rows([{"total_ms": 7_380_000}]) == "재생 시간: 2시간 3분입니다."


def test_track_top1_and_ranking():
    top = [{"title": "입춘", "artist": "한로로", "total_ms": 7_380_000}]
    assert format_rows(top) == "입춘 (한로로)입니다. (재생 시간 2시간 3분)"
    assert format_rows([{"title": "입춘"}]) == "입춘입니다."
    ranking = [
        {"title": "사건의 지평선", "artist": "윤하", "total_ms": 1_200_000, "play_count": 4},
        {"title": "입춘", "artist": "한로로", "total_ms": 780_000, "play_count": 4},
    ]
    assert format_rows(ranking) == ("1. 사건의 지평선 (윤하) — 재생 시간 20분, 청취 횟수 4회\n"
                                    "2. 입춘 (한로로) — 재생 시간 13분, 청취 횟수 4회")


def test_time_series():
    monthly = [{"month": datetime(2026, 10, 1), "total_ms": 18_000_000},
               {"month": datetime(2026, 11, 1), "total_ms": 1_140_000}]
    assert format_rows(monthly) == "2026년 10월: 재생 시간 5시간\n2026년 11월: 재생 시간 19분"
    weekdays = [{"weekday": Decimal("0"), "play_count": 2}, {"weekday": 6, "play_count": 1}]
    assert format_rows(weekdays) == "일요일: 청취 횟수 2회\n토요일: 청취 횟수 1회"


def test_other_shape_and_unknown_columns():
    assert format_rows([{"artist_count": 2, "foo_bar": "x"}]) == "가수 수 2개, foo_bar x"
    assert label("foo_bar") == "foo_bar" and label("sum_ms") == "재생 시간" and label("cnt") == "개수"


def test_none_and_unknown_note():
    assert format_rows([{"title": "입춘", "total_ms": None, "unknown_count": 3}]) == \
        "입춘입니다. (재생 시간 알 수 없음) (재생 시간 미확인 3건 제외)"
    assert format_rows([{"total_ms": 60_000, "unknown_count": 0}]) == "재생 시간: 1분입니다."
    assert format_rows([{"unknown_count": 2}]) == "재생 시간을 확인할 수 있는 기록이 없습니다. (재생 시간 미확인 2건 제외)"
    assert format_rows([]) == "조건에 맞는 청취 기록이 없습니다."


def test_value_formats():
    assert value("month", datetime(2026, 10, 1)) == "2026년 10월"
    assert value("week", datetime(2026, 11, 2)) == "11월 2일 주"
    assert value("day", date(2026, 11, 7)) == "2026년 11월 7일"
    # aware timestamps are shown in Asia/Seoul
    assert value("first_at", datetime(2026, 1, 1, 16, tzinfo=timezone.utc)) == "2026년 1월 2일"
    assert value("hour", 13) == "13시" and value("weekday", 7) == "일요일"


def test_rank_column_is_not_repeated():
    ranked = [{"rank": 1, "title": "입춘", "total_ms": 780_000}, {"rank": 1, "title": "봄", "total_ms": 780_000},
              {"rank": 3, "title": "밤", "total_ms": 60_000}]
    assert format_rows(ranked) == "1. 입춘 — 재생 시간 13분\n1. 봄 — 재생 시간 13분\n3. 밤 — 재생 시간 1분"  # RANK() ties kept
    assert format_rows(ranked[:1]) == "입춘입니다. (재생 시간 13분)"
