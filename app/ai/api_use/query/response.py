"""조회 결과를 한국어 응답 문장으로 만듭니다. (DB 결과는 LLM에 보내지 않고 템플릿으로 생성)"""
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.config import get_settings


def format_duration(ms: int) -> str:
    seconds = ms // 1000
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}시간")
    if minutes:
        parts.append(f"{minutes}분")
    if seconds or not parts:
        parts.append(f"{seconds}초")
    return " ".join(parts)


# Text-to-SQL 결과 열 이름 → 한국어. SQL_PROMPT(text_to_sql.py)의 열 이름 목록과 맞춰 둡니다.
LABELS = {
    "title": "곡", "artist": "가수", "album": "앨범",
    "total_ms": "재생 시간", "play_count": "청취 횟수", "track_count": "곡 수",
    "artist_count": "가수 수", "unknown_count": "시간 미확인",
    "first_at": "처음 기록", "last_at": "마지막 기록",
    "month": "월", "week": "주", "day": "날짜", "hour": "시", "weekday": "요일", "rank": "순위",
}
PERIODS = ("month", "week", "day", "hour", "weekday")
NUMBER = (int, float, Decimal)


def label(key: str) -> str:
    if key in LABELS:
        return LABELS[key]
    if key.endswith("_ms"):
        return "재생 시간"
    if key.endswith("_count") or key in ("n", "cnt", "count"):
        return "개수"
    return key  # 모르는 이름은 숨기지 않고 그대로


def _is_count(key: str) -> bool:
    return key.endswith("_count") or key in ("n", "cnt", "count")


def value(key: str, v) -> str:
    """표시용 값. 응답 JSON의 rows는 원래 값을 그대로 둡니다(앱에서 표를 그릴 수 있게)."""
    if v is None:
        return "알 수 없음"
    if key.endswith("_ms"):
        return format_duration(int(v))
    if isinstance(v, date):  # date_trunc 결과는 datetime, ::date 결과는 date
        if isinstance(v, datetime) and v.tzinfo is not None:
            v = v.astimezone(ZoneInfo(get_settings().display_timezone))
        if key == "month":
            return f"{v.year}년 {v.month}월"
        if key == "week":
            return f"{v.month}월 {v.day}일 주"
        return f"{v.year}년 {v.month}월 {v.day}일"
    if key == "weekday" and isinstance(v, NUMBER):
        return "일월화수목금토"[int(v) % 7] + "요일"  # PostgreSQL DOW(0=일), ISODOW(7=일) 모두
    if key == "hour" and isinstance(v, NUMBER):
        return f"{int(v)}시"
    if _is_count(key) and isinstance(v, NUMBER):
        return f"{int(v)}{'회' if key == 'play_count' else '개'}"
    return str(v)


def _track(row: dict) -> str:
    """"입춘 (한로로)"."""
    return f"{row['title']} ({row['artist']})" if row.get("artist") else str(row["title"])


def _rest(row: dict, keys: list[str], skip: str | None = None) -> str:
    """곡·기간 열을 뺀 나머지: "재생 시간 2시간 3분, 청취 횟수 14회"."""
    return ", ".join(f"{label(k)} {value(k, row[k])}" for k in keys if k not in ("title", "artist", skip))


def _unknown_note(rows: list[dict]) -> str:
    unknown = sum(int(row.get("unknown_count") or 0) for row in rows)
    return f" (재생 시간 미확인 {unknown}건 제외)" if unknown else ""


def format_rows(rows: list[dict], question: str = "") -> str:
    """Text-to-SQL 결과를 결과 모양(값 하나 / 곡 목록 / 시간 흐름 / 그 외)에 맞는 문장으로."""
    if not rows:
        return "조건에 맞는 청취 기록이 없습니다."
    note = _unknown_note(rows)
    keys = [k for k in rows[0] if k != "unknown_count"]
    if not keys:  # unknown_count만 있는 결과
        return f"재생 시간을 확인할 수 있는 기록이 없습니다.{note}"

    # ① 값 하나: "지난달에 들은 곡 몇 개야?" → 3곡입니다.
    if len(rows) == 1 and len(keys) == 1 and keys[0] != "title":
        key, v = keys[0], rows[0][keys[0]]
        if "곡" in question and _is_count(key) and key != "play_count" and isinstance(v, NUMBER):
            return f"{int(v)}곡입니다.{note}"
        return f"{label(key)}: {value(key, v)}입니다.{note}"

    # ② 곡이 있는 결과: 1위 한 곡 또는 순위·목록
    if "title" in keys:
        if len(rows) == 1:
            rest = _rest(rows[0], keys)
            return f"{_track(rows[0])}입니다.{f' ({rest})' if rest else ''}{note}"
        lines = []
        for i, row in enumerate(rows, 1):
            rest = _rest(row, keys)
            lines.append(f"{i}. {_track(row)}{f' — {rest}' if rest else ''}")
        return "\n".join(lines) + note

    # ③ 시간 흐름: month/week/day/hour/weekday 열 + 값
    period = next((k for k in PERIODS if k in keys), None)
    if period:
        return "\n".join(f"{value(period, row[period])}: {_rest(row, keys, skip=period)}" for row in rows) + note

    # ④ 그 외: 한국어 열 이름으로 나열
    return "\n".join(", ".join(f"{label(k)} {value(k, row[k])}" for k in keys) for row in rows) + note


def build_answer(first: datetime | None, total: int | None) -> tuple[str, datetime | None, int | None]:
    """(answer, first_recorded_at(UTC 보정), total_listened_ms)"""
    sentences = []
    if first is not None:
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        local = first.astimezone(ZoneInfo(get_settings().display_timezone))
        sentences.append(f"이 앱의 기록에서는 {local.year}년 {local.month}월 {local.day}일에 처음 확인되었습니다.")
    if total is not None:
        total = int(total)
        sentences.append(f"기록된 총 재생 시간은 {format_duration(total)}입니다.")
    return " ".join(sentences), first, total
