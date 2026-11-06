"""Treat every SQL proposal as untrusted; execute only a server-owned equivalent.

The AST must match a supported aggregate and both authenticated predicates.
This deliberately small language excludes joins, CTEs, subqueries, extra
functions/filters, comments, multiple statements, literals and query hints.
"""
from typing import Literal

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

Metric = Literal["first", "total", "both"]
FIRST = "MIN(observed_at) AS first_recorded_at"
TOTAL = "COALESCE(SUM(CAST(listened_ms AS BIGINT)), 0) AS total_listened_ms"
PREDICATES = "user_id = :authenticated_user_id AND track_id = :resolved_track_id"


def metric_sql(metric: Metric) -> str:
    fields = {"first": FIRST, "total": TOTAL, "both": f"{FIRST}, {TOTAL}"}[metric]
    return f"SELECT {fields} FROM listen_events WHERE {PREDICATES}"


class UnsafeSQL(ValueError):
    pass


def validate_sql(sql: str, metric: Metric) -> str:
    if len(sql) > 3000 or any(marker in sql for marker in ("--", "/*", "*/")):
        raise UnsafeSQL("SQL comments or excessive length")
    try:
        statements = parse(sql, read="postgres")
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            raise UnsafeSQL("Only a single SELECT is allowed")
        actual = statements[0]
        expected = parse(metric_sql(metric), read="postgres")[0]
        # Allow swapping the two AND terms, while requiring exactly both.
        actual_where = actual.args.get("where")
        expected_where = expected.args["where"]
        if actual_where is None or not isinstance(actual_where.this, exp.And):
            raise UnsafeSQL("Authenticated filters are required")
        a, b = actual_where.this.this, actual_where.this.expression
        x, y = expected_where.this.this, expected_where.this.expression
        if not ((a == x and b == y) or (a == y and b == x)):
            raise UnsafeSQL("Unexpected filters")
        actual.set("where", expected_where.copy())
        if actual != expected:
            raise UnsafeSQL("Unsupported query shape or metric")
    except SqlglotError as error:
        raise UnsafeSQL("Malformed SQL") from error
    # Never execute the original string, even when its AST was accepted.
    return metric_sql(metric)

