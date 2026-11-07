"""챗봇 흐름: 질문 분류 → (곡별 지표) 곡 확정 → 고정 SQL / (자유 통계) Text-to-SQL → 응답 생성."""
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.ai.api_use.chat_classify import classify_question
from app.ai.api_use.query.executor import run_metric
from app.ai.api_use.query.response import build_answer, format_rows
from app.ai.api_use.text_to_sql import run_stats
from app.models import Track, ListenEvent
from app.schemas import ChatInput, ChatOut, TrackOut
from app.services.track_service import owned_track

UNSPECIFIED_TITLES = ("이 노래", "이 곡", "그 노래", "그 곡", "", "내", "제")


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
    metric, title = classify_question(request.question)
    if metric is None:
        return ChatOut(status="unsupported", answer="본인 곡의 최초 기록일과 기록된 총 재생 시간을 조회할 수 있습니다. 곡명과 함께 질문해 주세요.")
    if metric == "stats":
        rows = run_stats(session, user_id, request.question)
        if rows is None:
            return ChatOut(status="unsupported", metric="stats", answer="이 통계 질문은 처리하지 못했습니다. 질문을 바꿔 다시 시도해 주세요.")
        return ChatOut(status="answered" if rows else "not_found", metric="stats", answer=format_rows(rows), rows=rows)
    if request.track_id:
        track = owned_track(session, user_id, request.track_id)
    else:
        if title in UNSPECIFIED_TITLES:
            return ChatOut(status="needs_track", metric=metric, answer="조회할 곡을 선택하거나 곡명을 알려 주세요.")
        candidates = find_candidates(session, user_id, title)
        if not candidates:
            return ChatOut(status="not_found", metric=metric, answer="해당 곡의 청취 기록이 없습니다.")
        if len(candidates) != 1:
            return ChatOut(status="ambiguous", metric=metric,
                           answer="같은 이름의 곡이 여러 개 있습니다. 곡을 선택해 다시 질문해 주세요.",
                           candidates=[TrackOut.model_validate(t) for t in candidates[:20]])
        track = candidates[0]

    first, total = run_metric(session, metric, user_id, track.id)
    unknown = session.scalar(select(func.count()).select_from(ListenEvent).where(
        ListenEvent.user_id == user_id, ListenEvent.track_id == track.id, ListenEvent.listened_ms.is_(None)))
    if unknown and metric in ("total", "both") and not total:
        answer, first, _ = build_answer(first, None)
        return ChatOut(status="answered", metric=metric, track=TrackOut.model_validate(track),
                       first_recorded_at=first, total_listened_ms=None,
                       answer=(answer + " 청취 시각 기록은 있지만 재생 시간을 알 수 없어 총 시간을 계산할 수 없습니다.").strip())
    # For total-only queries, absence must be determined separately: SUM=0 is
    # not a license to invent a first date.
    if (metric in ("first", "both") and first is None) or (metric == "total" and not total):
        return ChatOut(status="not_found", metric=metric, track=TrackOut.model_validate(track),
                       answer="해당 곡의 청취 기록이 없습니다.")
    answer, first, total = build_answer(first, total)
    if unknown and total is not None:
        answer += f" 재생 시간을 확인할 수 없는 가져오기 기록 {unknown}건은 시간 합계에서 제외했습니다."
    return ChatOut(status="answered", metric=metric, answer=answer,
                   track=TrackOut.model_validate(track), first_recorded_at=first, total_listened_ms=total)
