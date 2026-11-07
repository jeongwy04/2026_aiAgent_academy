"""조회 결과를 한국어 응답 문장으로 만듭니다. (DB 결과는 LLM에 보내지 않고 템플릿으로 생성)"""
from datetime import datetime, timezone
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
