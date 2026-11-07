"""자유 통계 질문용 Text-to-SQL: LLM이 SQL 작성 → 전용 검증기 → 실행, 실패 시 최대 3회 재작성(self-healing).

실행 세션은 읽기 전용 계정·강제 RLS·쿼리 시간 제한이 걸린 ReadSession이고,
검증기가 모든 테이블을 본인 행으로 한정한 SQL만 실행합니다.
"""
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.api_use.chat_classify import chat_model
from app.ai.api_use.query.stats_validator import MAX_ROWS, guard_stats_sql
from app.ai.api_use.query.validator import UnsafeSQL
from app.config import get_settings

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
SQL_PROMPT = """너는 PostgreSQL 전문가다. 사용자 본인의 음악 청취 기록 통계 질문을 SELECT 문 하나로 작성하라.

테이블 (이미 현재 사용자 데이터로 한정되어 있으므로 user_id 조건을 쓰지 마라):
- listen_events(track_id uuid, observed_at timestamptz UTC 저장, listened_ms bigint nullable: 관찰한 재생 시간 ms, source text)
- tracks(id uuid, title text, artist text, album text)
- 조인: listen_events.track_id = tracks.id

규칙:
- 날짜·월·요일 계산은 observed_at AT TIME ZONE '{tz}' 기준.
- 오늘·이번 주·이번 달·지난달·작년 같은 기준 시점은 반드시 now() AT TIME ZONE '{tz}'로 계산하라 (CURRENT_DATE 금지).
- 재생 시간 열 이름은 _ms로 끝나게 하라 (예: total_ms).
- source='google_takeout_my_activity'의 listened_ms는 알 수 없어 NULL이다. 0초나 30초로 대체하지 마라. 시간 질문에는 SUM(listened_ms)와 COUNT(listened_ms), COUNT(*)-COUNT(listened_ms)를 함께 반환해 미확인 건수를 구분하라.
- LIMIT은 {max_rows} 이하. CTE(WITH), UNION, 주석, 세미콜론, 파라미터는 쓰지 마라.
- 설명이나 마크다운 없이 SQL만 출력하라."""


def _clean(content: str) -> str:
    sql = re.sub(r"^\s*```(?:sql)?|```\s*$", "", str(content).strip(), flags=re.IGNORECASE).strip()
    return sql.rstrip("; \n")


def _plain(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


@dataclass
class StatsResult:
    rows: list[dict] | None  # None: LLM 오류 또는 3회 모두 실패
    attempts: list[dict] = field(default_factory=list)  # [{"sql": ..., "error": str | None}, ...]


def run_stats(session: Session, user_id: UUID, question: str) -> StatsResult:
    """결과 행(최대 50행)과 시도별 생성 SQL. "오늘"은 프롬프트·평가 모두 DB의 now() 기준."""
    settings = get_settings()
    system = SQL_PROMPT.format(tz=settings.display_timezone, max_rows=MAX_ROWS)
    result = StatsResult(rows=None)
    messages = [("system", system), ("human", question)]
    dialect = session.bind.dialect.name
    try:
        llm = chat_model(settings.pickle_api_key, settings.chat_model, settings.llm_base_url)
        for _ in range(MAX_ATTEMPTS):
            sql = _clean(llm.invoke(messages).content)
            try:
                safe = guard_stats_sql(sql, user_id, dialect)
                with session.begin_nested():  # A failed statement must not abort the request transaction.
                    rows = session.connection().exec_driver_sql(safe).mappings().fetchmany(MAX_ROWS)
                # Aggregates over no rows return one all-NULL row: that means "no records".
                result.rows = [{key: _plain(value) for key, value in row.items()} for row in rows
                               if any(value is not None for value in row.values())]
                result.attempts.append({"sql": sql, "error": None})
                break
            except (UnsafeSQL, SQLAlchemyError) as error:
                feedback = str(getattr(error, "orig", None) or error)[:300]
                result.attempts.append({"sql": sql, "error": feedback})
                messages += [("ai", sql), ("human", f"이 SQL은 실패했습니다: {feedback}\n규칙을 지켜 고친 SQL만 다시 출력하라.")]
    except Exception:
        logger.warning("Text-to-SQL LLM call failed", exc_info=True)
    # Generated SQL can contain song titles from the question: DEBUG only, never shown to
    # end users (see CHAT_DEBUG). INFO keeps just the outcome.
    logger.info("Text-to-SQL attempts=%s ok=%s", len(result.attempts), result.rows is not None)
    logger.debug("Text-to-SQL attempts detail: %s", result.attempts)
    return result
