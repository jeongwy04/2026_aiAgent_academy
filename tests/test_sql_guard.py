import pytest

from app.ai.api_use.query.validator import UnsafeSQL, metric_sql, validate_sql


@pytest.mark.parametrize("metric", ["first", "total", "both"])
def test_canonical_query(metric):
    sql = metric_sql(metric)
    assert validate_sql(sql, metric) == sql
    assert validate_sql(sql.lower(), metric) == sql
    reordered = sql.replace("user_id = :authenticated_user_id AND track_id = :resolved_track_id",
                            "track_id = :resolved_track_id AND user_id = :authenticated_user_id")
    assert validate_sql(reordered, metric) == sql


BASE = metric_sql("both")


@pytest.mark.parametrize("sql", [
    "DELETE FROM listen_events", "SELECT * FROM members", "SELECT 1", "",
    BASE + "; SELECT 1", BASE + " UNION SELECT 1, 2", BASE + " -- bypass",
    BASE.replace("listen_events", "members"),
    BASE.replace("listen_events", "other.listen_events"),
    BASE.replace("listen_events", "listen_events JOIN tracks ON true"),
    "WITH x AS (" + BASE + ") SELECT * FROM x",
    BASE.replace("MIN(observed_at)", "MAX(observed_at)"),
    BASE.replace("SUM(CAST(listened_ms AS BIGINT))", "SUM(listened_ms + 1)"),
    BASE.replace(":authenticated_user_id", "'victim'"),
    BASE.replace(":authenticated_user_id", ":user_id"),
    BASE.replace(" AND track_id = :resolved_track_id", ""),
    BASE.replace(" AND ", " OR "), BASE + " OR 1=1", BASE + " AND listened_ms > 30000",
    BASE + " ORDER BY pg_sleep(10)", BASE + " LIMIT 1", BASE + " FOR UPDATE",
    BASE.replace("MIN(observed_at)", "(SELECT MIN(observed_at) FROM listen_events)"),
    BASE.replace("MIN(observed_at)", "pg_sleep(100)"),
    BASE.replace("SELECT", "SELECT /* comment */", 1),
    "EXPLAIN " + BASE,
    BASE.replace("FROM", "INTO stolen FROM", 1),
])
def test_unsafe_queries_rejected(sql):
    with pytest.raises(UnsafeSQL):
        validate_sql(sql, "both")


def test_wrong_metric_rejected():
    with pytest.raises(UnsafeSQL):
        validate_sql(metric_sql("first"), "total")

