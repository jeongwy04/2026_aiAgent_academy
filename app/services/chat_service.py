"""챗봇 흐름: 질문 분류 → (곡별 지표) 곡 확정 → 고정 SQL / (자유 통계) Text-to-SQL → 응답 생성."""
import re
from uuid import UUID

from sqlalchemy import func, literal, select
from sqlalchemy.orm import Session

from app.ai.api_use.chat_classify import classify_question
from app.ai.api_use.query.executor import run_metric
from app.ai.api_use.query.response import build_answer, format_rows
from app.ai.api_use.summary import summarize
from app.ai.api_use.text_to_sql import run_stats
from app.config import get_settings
from app.models import Track, ListenEvent
from app.schemas import ChatInput, ChatOut, TrackOut
from app.services.track_service import owned_track
from app.utils import normalized

UNSUPPORTED = ("본인 청취 기록만 조회할 수 있습니다. 곡별 최초 기록일·총 재생 시간(예: '입춘 언제부터 들었어?')이나 "
               "'이번 달 가장 많이 들은 곡', '월별 청취 시간' 같은 통계를 질문해 주세요.")
# "이 노래", "이노래", "이 노래를", "그 곡은", "저 노래", "이 노래 제"(README 예시), "이 곡 내"
DEICTIC = re.compile(r"(?:이|그|저)\s*(?:노래|곡)(?:을|를|은|는|이|가|의)?(?:\s*(?:내|제|나의))?")


def is_unspecified(title: str) -> bool:
    """제목 전체가 '이 노래' 같은 지시어일 때만 True. '이 노래가 좋아' 같은 실제 제목은 False."""
    t = normalized(title)
    return t in ("", "내", "제") or DEICTIC.fullmatch(t) is not None


def titles_in_question(session: Session, user_id: UUID, question: str) -> list[str]:
    """질문 안에 들어 있는 본인 곡 제목(2글자 이상). 분류 정규식 검사에서 지우는 용도.
    ReadSession(읽기 전용 + RLS)에서 호출하므로 본인 곡만 조회됩니다."""
    found = session.scalars(
        select(Track.title).where(
            Track.user_id == user_id,
            func.length(Track.title) >= 2,
            literal(question.lower()).contains(func.lower(Track.title)),  # :q LIKE '%' || lower(title) || '%'
        ).distinct().limit(20)
    ).all()
    q = normalized(question)
    return [t for t in found if normalized(t) in q]  # 제목 속 %·_ 와일드카드로 잘못 걸린 경우를 제외


def find_candidates(session: Session, user_id: UUID, title: str) -> list[Track]:
    """정확히 일치하는 제목을 먼저 찾고, 없으면 부분 일치. 최대 21개."""
    # Exact normalized titles, then literal substring fallback. SQL wildcards
    # in the question have no special meaning (and library size is bounded).
    escaped = title.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    # Candidate retrieval stays bounded; ambiguous results never execute SQL.
    query = select(Track).where(Track.user_id == user_id).order_by(Track.title, Track.artist, Track.id).limit(21)
    candidates = list(session.scalars(query.where(Track.title.ilike(escaped, escape="\\"))))
    if not candidates:
        candidates = list(session.scalars(query.where(Track.title.ilike(f"%{escaped}%", escape="\\"))))
    return candidates


def answer_question(session: Session, user_id: UUID, request: ChatInput) -> ChatOut:
    metric, title = classify_question(request.question, titles_in_question(session, user_id, request.question))
    if metric is None:
        return ChatOut(question=request.question, status="unsupported", answer=UNSUPPORTED)
    if metric == "stats":
        settings = get_settings()
        result = run_stats(session, user_id, request.question)
        debug = {"sql_attempts": result.attempts} if settings.chat_debug else None
        if result.rows is None:
            return ChatOut(question=request.question, status="unsupported", metric="stats", debug=debug,
                           answer="이 통계 질문은 처리하지 못했습니다. 질문을 바꿔 다시 시도해 주세요.")
        answer = format_rows(result.rows, request.question)
        # Single row only: in multi-row (ranking) results the guard can't catch swapped
        # track/number pairs, and the numbered template already reads well.
        if settings.chat_llm_summary and len(result.rows) == 1:
            answer, summary_info = summarize(request.question, result.rows, answer)
            if debug is not None:
                debug["summary"] = summary_info
        return ChatOut(question=request.question, status="answered" if result.rows else "not_found", metric="stats", debug=debug,
                       answer=answer, rows=result.rows)
    if request.track_id:
        track = owned_track(session, user_id, request.track_id)
    else:
        if is_unspecified(title):
            return ChatOut(question=request.question, status="needs_track", metric=metric, answer="조회할 곡을 선택하거나 곡명을 알려 주세요.")
        candidates = find_candidates(session, user_id, title)
        if not candidates:
            return ChatOut(question=request.question, status="not_found", metric=metric, answer="해당 곡의 청취 기록이 없습니다.")
        if len(candidates) != 1:
            return ChatOut(question=request.question, status="ambiguous", metric=metric,
                           answer="같은 이름의 곡이 여러 개 있습니다. 곡을 선택해 다시 질문해 주세요.",
                           candidates=[TrackOut.model_validate(t) for t in candidates[:20]])
        track = candidates[0]

    first, total = run_metric(session, metric, user_id, track.id)
    unknown = session.scalar(select(func.count()).select_from(ListenEvent).where(
        ListenEvent.user_id == user_id, ListenEvent.track_id == track.id, ListenEvent.listened_ms.is_(None)))
    if unknown and metric in ("total", "both") and not total:
        answer, first, _ = build_answer(first, None)
        return ChatOut(question=request.question, status="answered", metric=metric, track=TrackOut.model_validate(track),
                       first_recorded_at=first, total_listened_ms=None,
                       answer=(answer + " 청취 시각 기록은 있지만 재생 시간을 알 수 없어 총 시간을 계산할 수 없습니다.").strip())
    # For total-only queries, absence must be determined separately: SUM=0 is
    # not a license to invent a first date.
    if (metric in ("first", "both") and first is None) or (metric == "total" and not total):
        return ChatOut(question=request.question, status="not_found", metric=metric, track=TrackOut.model_validate(track),
                       answer="해당 곡의 청취 기록이 없습니다.")
    answer, first, total = build_answer(first, total)
    if unknown and total is not None:
        answer += f" 재생 시간을 확인할 수 없는 가져오기 기록 {unknown}건은 시간 합계에서 제외했습니다."
    return ChatOut(question=request.question, status="answered", metric=metric, answer=answer,
                   track=TrackOut.model_validate(track), first_recorded_at=first, total_listened_ms=total)
