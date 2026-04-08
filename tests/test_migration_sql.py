"""SQL splitting for Alembic baseline."""

from __future__ import annotations

from core.migration_sql import SQL_BASELINE_FILES, iter_statements, normalize_baseline_sql_paths


def test_iter_statements_splits_simple() -> None:
    sql = "SELECT 1;\nSELECT 2;"
    parts = iter_statements(sql)
    assert len(parts) == 2


def test_iter_statements_skips_comment_only() -> None:
    sql = "-- just a comment\n  \n"
    assert iter_statements(sql) == []


def test_normalize_baseline_sql_paths_orders_schema_then_auth() -> None:
    shuffled = (
        "db/approvals_table.sql",
        "db/db_schema.sql",
        "db/auth_rbac.sql",
        "db/learning_logs.sql",
    )
    # CORE → PRE (no users FK) → IDENTITY → POST (users FK)
    assert normalize_baseline_sql_paths(shuffled) == [
        "db/db_schema.sql",
        "db/auth_rbac.sql",
        "db/approvals_table.sql",
        "db/learning_logs.sql",
    ]


def test_normalize_baseline_sql_paths_pre_identity_before_auth() -> None:
    """Org-only SQL runs before auth; user-FK files run after auth even if listed first."""
    shuffled = (
        "db/life_os.sql",
        "db/db_schema.sql",
        "db/notifications_alerts.sql",
        "db/auth_rbac.sql",
        "db/approvals_table.sql",
    )
    assert normalize_baseline_sql_paths(shuffled) == [
        "db/db_schema.sql",
        "db/notifications_alerts.sql",
        "db/auth_rbac.sql",
        "db/life_os.sql",
        "db/approvals_table.sql",
    ]


def test_normalize_baseline_sql_paths_dedupes() -> None:
    assert normalize_baseline_sql_paths(
        ["db/db_schema.sql", "db/auth_rbac.sql", "db/db_schema.sql"]
    ) == ["db/db_schema.sql", "db/auth_rbac.sql"]


def test_normalize_sql_baseline_files_migrate_roles_after_auth() -> None:
    ordered = normalize_baseline_sql_paths(SQL_BASELINE_FILES)
    assert ordered.index("db/auth_rbac.sql") < ordered.index("db/migrate_roles_add_org_id.sql")
    assert ordered.index("db/auth_rbac.sql") < ordered.index("db/life_os.sql")
