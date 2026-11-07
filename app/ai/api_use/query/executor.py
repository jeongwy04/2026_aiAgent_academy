"""검증된 집계 SQL만 실행합니다. 파라미터는 서버가 확정한 사용자·곡 ID로만 채웁니다."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.api_use.query.validator import Metric, metric_sql, validate_sql


def run_metric(session: Session, metric: Metric, user_id: UUID, track_id: UUID) -> tuple[datetime | None, int | None]:
    """(first_recorded_at, total_listened_ms). 요청하지 않은 지표는 None입니다."""
    # Baseline proposal provider. A future LLM tool-call adapter can propose SQL
    # here; it must go through the same validator and server-bound parameters.
    sql = validate_sql(metric_sql(metric), metric)
    params = {"authenticated_user_id": user_id, "resolved_track_id": track_id}
    if session.bind.dialect.name == "sqlite":
        params = {key: value.hex for key, value in params.items()}
    row = session.execute(text(sql), params).mappings().one()
    first = row.get("first_recorded_at")
    total = row.get("total_listened_ms")
    if isinstance(first, str):
        first = datetime.fromisoformat(first)
    return first, total
