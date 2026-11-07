"""평가 채점: 경로(status·metric), 값(compare 방식별), 유출 없음. 응답 시간은 합격 판정과 분리해 따로 봅니다.

행 비교는 LLM이 붙이는 열 이름(total_ms, sum_ms, 재생시간_ms ...)을 무시하고 값만 봅니다.
각 기준 행의 값이 실제 행의 값 안에 모두 있으면 같은 행으로 봅니다. 그래서 LLM이 가수명 같은
열을 더 붙여도 통과합니다. 숫자는 Decimal·int·float를 같게, 날짜는 한국 날짜 문자열로 맞춥니다.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
MAX_SECONDS = 10.0


def _as_datetime(value) -> datetime | date | None:
    if isinstance(value, (datetime, date)):
        return value
    if isinstance(value, str) and len(value) >= 10 and value[4] == "-" and value[7] == "-":
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def kst_date(value) -> str | None:
    moment = _as_datetime(value)
    if isinstance(moment, datetime) and moment.tzinfo is not None:
        moment = moment.astimezone(KST)
    return moment.strftime("%Y-%m-%d") if moment is not None else None


def forms(value) -> set[str]:
    """값을 비교용 문자열 집합으로. 한 값이 여러 표기로 맞을 수 있으면 모두 넣습니다."""
    if value is None:
        return {"null"}
    if isinstance(value, bool):
        return {str(value).lower()}
    moment = _as_datetime(value)
    if moment is not None:
        if isinstance(moment, datetime) and moment.tzinfo is not None:
            moment = moment.astimezone(KST)
        day = moment.strftime("%Y-%m-%d")
        result = {day}
        if moment.day == 1 and (not isinstance(moment, datetime) or moment.time() == datetime.min.time()):
            result.add(moment.strftime("%Y-%m"))  # date_trunc('month') ≡ 'YYYY-MM'
        return result
    try:
        number = Decimal(str(value))
        if number.is_finite():
            return {format(number.normalize(), "f")}
    except (InvalidOperation, ValueError):
        pass
    return {str(value).strip().casefold()}


def row_matches(expected: dict, actual: dict) -> bool:
    actual_forms = set().union(*(forms(v) for v in actual.values())) if actual else set()
    return all(forms(v) & actual_forms for v in expected.values())


def compare_rows(expected: list[dict], actual: list[dict], mode: str) -> bool:
    if mode == "top1":
        return bool(expected) and bool(actual) and row_matches(expected[0], actual[0])
    if len(expected) != len(actual):
        return False
    if mode == "rows_ordered":
        return all(row_matches(e, a) for e, a in zip(expected, actual))
    remaining = list(actual)  # rows_unordered: one-to-one matching
    for e in expected:
        match = next((a for a in remaining if row_matches(e, a)), None)
        if match is None:
            return False
        remaining.remove(match)
    return True


def compare_value(mode: str, expected: list[dict], response: dict) -> bool:
    """expected: 기준 SQL 결과 행. 곡별 지표의 기준 SQL은 열 순서가 (first, total)입니다."""
    if mode == "none":
        return True
    if mode in ("first_date", "total_ms", "both"):
        values = list(expected[0].values()) if expected else []
        if mode == "first_date":
            return kst_date(response.get("first_recorded_at")) == kst_date(values[0])
        if mode == "total_ms":
            return response.get("total_listened_ms") == int(values[1])
        return (kst_date(response.get("first_recorded_at")) == kst_date(values[0])
                and response.get("total_listened_ms") == int(values[1]))
    return compare_rows(expected, response.get("rows") or [], mode)


def score(item: dict, expected: list[dict], response: dict, seconds: float, leak_markers: list[str]) -> dict:
    """항목별 합격 여부. route·value·no_leak이 모두 True여야 passed.
    time(10초 이내)은 리포트용입니다. stats는 LLM을 2~4번 부르므로 정확도와 속도를 섞지 않습니다."""
    expect = item.get("expect", {})
    route = all(response.get(key) == value for key, value in expect.items() if key in ("status", "metric"))
    if "candidates" in expect:
        route = route and len(response.get("candidates") or []) == expect["candidates"]
    text = str(response)
    checks = {
        "route": route,
        "value": route and compare_value(item.get("compare", "none"), expected, response),
        "no_leak": not any(marker in text for marker in leak_markers),
        "time": seconds <= MAX_SECONDS,
    }
    return {"passed": checks["route"] and checks["value"] and checks["no_leak"], **checks}
