import re
from datetime import datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.listening import normalized, owned_track
from app.models import Track
from app.schemas import ChatInput, ChatOut, TrackOut
from app.sql_guard import Metric, metric_sql, validate_sql


def classify(question: str) -> Metric | None:
    q = normalized(question)
    # Fail closed for modifications, third-party data and out-of-scope dimensions.
    if re.search(r"다른\s*(사용자|사람|회원)|타인|전체\s*(사용자|회원)|삭제|수정|변경|업데이트|drop|insert|update|delete|;|--|/\*|이번\s*달|지난\s*달|월별|기간별|가장|랭킹|순위|오늘|어제|작년|올해|지난주|이번주|지난달|이번달|지난\s*주|이번\s*주|\d+\s*년|\d+\s*월|\d+\s*일|부터.*까지", q):
        return None
    first = bool(re.search(r"최초|처음|언제.*(듣|들|기록)|언제부터", q))
    total = bool(re.search(r"총.*(시간|재생|들었|듣)|얼마나|몇\s*(시간|분|초)|재생\s*시간", q))
    if first and total:
        return "both"
    if first:
        return "first"
    if total:
        return "total"
    return None


def extract_title(question: str) -> str:
    quoted = re.search(r"[\"'“‘](.+?)[\"'”’]", question)
    if quoted:
        return normalized(quoted.group(1))
    q = normalized(question).rstrip("?!., ")
    q = re.sub(r"^(저는|나는|제가|내가)\s+", "", q)
    q = re.split(r"\s+(?:언제|처음|최초|총|얼마나|몇\s*(?:시간|분|초)|재생\s*시간)", q, maxsplit=1)[0]
    q = re.sub(r"(?:의|은|는|을|를)$", "", q).strip()
    return q


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


def answer_question(session: Session, user_id: UUID, request: ChatInput) -> ChatOut:
    metric = classify(request.question)
    if metric is None:
        return ChatOut(status="unsupported", answer="본인 곡의 최초 기록일과 기록된 총 재생 시간을 조회할 수 있습니다. 곡명과 함께 질문해 주세요.")
    if request.track_id:
        track = owned_track(session, user_id, request.track_id)
    else:
        title = extract_title(request.question)
        if title in ("이 노래", "이 곡", "그 노래", "그 곡", "", "내", "제"):
            return ChatOut(status="needs_track", metric=metric, answer="조회할 곡을 선택하거나 곡명을 알려 주세요.")
        # Exact normalized titles, then literal substring fallback. SQL wildcards
        # in the question have no special meaning (and library size is bounded).
        escaped = title.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        # Candidate retrieval stays bounded; ambiguous results never execute SQL.
        query = select(Track).where(Track.user_id == user_id).order_by(Track.title, Track.artist, Track.id).limit(21)
        candidates = list(session.scalars(query.where(Track.title.ilike(escaped, escape="\\"))))
        if not candidates:
            candidates = list(session.scalars(query.where(Track.title.ilike(f"%{escaped}%", escape="\\"))))
        if not candidates:
            return ChatOut(status="not_found", metric=metric, answer="해당 곡의 청취 기록이 없습니다.")
        if len(candidates) != 1:
            return ChatOut(status="ambiguous", metric=metric,
                           answer="같은 이름의 곡이 여러 개 있습니다. 곡을 선택해 다시 질문해 주세요.",
                           candidates=[TrackOut.model_validate(t) for t in candidates[:20]])
        track = candidates[0]

    # Baseline proposal provider. A future LLM tool-call adapter can propose SQL
    # here; it must go through the same validator and server-bound parameters.
    sql = validate_sql(metric_sql(metric), metric)
    params = {"authenticated_user_id": user_id, "resolved_track_id": track.id}
    if session.bind.dialect.name == "sqlite":
        params = {key: value.hex for key, value in params.items()}
    row = session.execute(text(sql), params).mappings().one()
    first = row.get("first_recorded_at")
    total = row.get("total_listened_ms")
    if isinstance(first, str):
        first = datetime.fromisoformat(first)
    # For total-only queries, absence must be determined separately: SUM=0 is
    # not a license to invent a first date.
    if (metric in ("first", "both") and first is None) or (metric == "total" and not total):
        return ChatOut(status="not_found", metric=metric, track=TrackOut.model_validate(track),
                       answer="해당 곡의 청취 기록이 없습니다.")
    sentences = []
    if first is not None:
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        local = first.astimezone(ZoneInfo(get_settings().display_timezone))
        sentences.append(f"이 앱의 기록에서는 {local.year}년 {local.month}월 {local.day}일에 처음 확인되었습니다.")
    if total is not None:
        total = int(total)
        sentences.append(f"기록된 총 재생 시간은 {format_duration(total)}입니다.")
    return ChatOut(status="answered", metric=metric, answer=" ".join(sentences),
                   track=TrackOut.model_validate(track), first_recorded_at=first, total_listened_ms=total)

