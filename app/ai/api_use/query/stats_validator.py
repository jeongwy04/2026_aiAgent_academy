"""자유 통계 질문(Text-to-SQL) 전용 검증기.

고정 SQL 검증기(validator.py)와 달리 LLM이 만든 다양한 SELECT를 허용하되,
허용 목록에 없는 문법·함수·테이블은 모두 거절합니다(fail closed).
통과한 SQL도 모든 테이블을 `user_id = <서버가 확정한 UUID>` 서브쿼리로
바꿔 실행하므로, LLM이 사용자 필터를 빠뜨리거나 조작해도 본인 데이터만 읽습니다.
(DB 계층의 읽기 전용 계정·강제 RLS·쿼리 시간 제한은 그대로 함께 적용됩니다.)
"""
from uuid import UUID

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

from app.ai.api_use.query.validator import UnsafeSQL

ALLOWED_TABLES = {"listen_events", "tracks"}
# Node whitelist: anything else (CTE, UNION, INTO, FOR UPDATE, placeholders,
# unknown functions such as set_config/pg_sleep, other schemas...) is rejected.
ALLOWED_NODES = (
    exp.Select, exp.From, exp.Join, exp.Where, exp.Group, exp.Having, exp.Order, exp.Ordered,
    exp.Limit, exp.Offset, exp.Subquery, exp.Paren, exp.Alias, exp.TableAlias, exp.Table,
    exp.Column, exp.Identifier, exp.Star, exp.Literal, exp.Null, exp.Boolean, exp.Var,
    exp.DataType, exp.DataTypeParam, exp.Interval, exp.Distinct, exp.Window, exp.AtTimeZone,
    exp.And, exp.Or, exp.Not, exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE,
    exp.Between, exp.In, exp.Is, exp.Like, exp.ILike,
    exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.Neg,
    exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max, exp.Coalesce, exp.Cast, exp.Round, exp.Floor,
    exp.Lower, exp.Upper, exp.Extract, exp.TimestampTrunc, exp.DateTrunc, exp.TimeToStr,
    exp.Case, exp.If, exp.CurrentDate, exp.CurrentTimestamp, exp.Rank, exp.DenseRank, exp.RowNumber,
)
SQLGLOT_DIALECT = {"postgresql": "postgres", "sqlite": "sqlite"}


def guard_stats_sql(sql: str, user_id: UUID, dialect: str = "postgresql") -> str:
    """검증 후 실행할 SQL(사용자 범위 강제 적용본)을 돌려줍니다. 실패 시 UnsafeSQL."""
    if not sql or len(sql) > 3000 or any(marker in sql for marker in ("--", "/*", "*/")):
        raise UnsafeSQL("SQL이 비어 있거나 너무 길거나 주석을 포함합니다.")
    try:
        statements = parse(sql, read="postgres")
    except SqlglotError as error:
        raise UnsafeSQL(f"SQL 문법 오류: {error}") from error
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise UnsafeSQL("SELECT 문 하나만 허용됩니다.")
    tree = statements[0]
    for node in tree.walk():
        if not isinstance(node, ALLOWED_NODES):
            raise UnsafeSQL(f"허용되지 않는 SQL 요소입니다: {node.sql(dialect='postgres')[:80]}")
        if isinstance(node, exp.Table) and (
            node.name not in ALLOWED_TABLES or node.args.get("db") or node.args.get("catalog")
            or not isinstance(node.this, exp.Identifier)
        ):
            raise UnsafeSQL(f"허용되지 않는 테이블입니다: {node.sql(dialect='postgres')}. listen_events, tracks만 사용하세요.")
    # Never trust the model's own user filter: every table becomes a scoped subquery.
    # The server-owned UUID is inlined as a sqlglot-quoted literal, so the result
    # runs without bind parameters (no `:name`/`%` parsing of the model's literals).
    user = exp.Literal.string(user_id.hex) if dialect == "sqlite" else exp.cast(exp.Literal.string(str(user_id)), "uuid")
    for table in list(tree.find_all(exp.Table)):
        scoped = exp.select("*").from_(table.name).where(exp.column("user_id").eq(user)).subquery(table.alias_or_name)
        table.replace(scoped)
    return tree.sql(dialect=SQLGLOT_DIALECT.get(dialect, "postgres"))
