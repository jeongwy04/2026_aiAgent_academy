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



STATS_USER = __import__("uuid").UUID("11111111-1111-1111-1111-111111111111")


def test_stats_sql_is_scoped_to_user():
    from app.ai.api_use.query.stats_validator import guard_stats_sql
    sql = ("SELECT t.title, SUM(e.listened_ms) AS total_ms FROM listen_events e JOIN tracks t ON t.id = e.track_id "
           "WHERE DATE_TRUNC('month', e.observed_at AT TIME ZONE 'Asia/Seoul') = DATE '2026-11-01' "
           "GROUP BY t.title ORDER BY total_ms DESC LIMIT 5")
    safe = guard_stats_sql(sql, STATS_USER)
    assert safe.count(f"user_id = CAST('{STATS_USER}' AS UUID)") == 2
    # A model-written filter for another user is kept but can only narrow the scoped subquery.
    other = guard_stats_sql("SELECT COUNT(*) FROM tracks WHERE user_id <> user_id", STATS_USER)
    assert guard_stats_sql("SELECT title FROM tracks", STATS_USER).endswith("LIMIT 50")
    assert guard_stats_sql("SELECT title FROM tracks LIMIT 1000", STATS_USER).endswith("LIMIT 50")
    assert guard_stats_sql("SELECT title FROM tracks LIMIT 5", STATS_USER).endswith("LIMIT 5")
    assert f"(SELECT * FROM tracks WHERE user_id = CAST('{STATS_USER}' AS UUID)) AS tracks" in other


@pytest.mark.parametrize("sql", [
    "", "DELETE FROM listen_events", "SELECT * FROM members", "SELECT * FROM auth_sessions",
    "SELECT 1; DELETE FROM tracks", "WITH x AS (SELECT 1) SELECT * FROM x", "SELECT * FROM public.tracks",
    "SELECT * FROM pg_catalog.pg_roles", "SELECT * FROM tracks UNION SELECT * FROM tracks",
    "SELECT * INTO t2 FROM tracks", "SELECT * FROM tracks FOR UPDATE", "SELECT pg_sleep(5)",
    "SELECT set_config('app.user_id', 'x', true)", "SELECT current_setting('app.user_id')",
    "SELECT * FROM generate_series(1, 10)", "SELECT * FROM tracks WHERE user_id = :authenticated_user_id",
    "SELECT * FROM tracks -- x", "SELECT * FROM tracks /* x */", "SELECT CURRENT_DATE",
])
def test_stats_sql_rejects_unsafe(sql):
    from app.ai.api_use.query.stats_validator import guard_stats_sql
    with pytest.raises(UnsafeSQL):
        guard_stats_sql(sql, STATS_USER)
