"""SQL splitting for Alembic baseline."""

from __future__ import annotations

from core.migration_sql import iter_statements


def test_iter_statements_splits_simple() -> None:
    sql = "SELECT 1;\nSELECT 2;"
    parts = iter_statements(sql)
    assert len(parts) == 2


def test_iter_statements_skips_comment_only() -> None:
    sql = "-- just a comment\n  \n"
    assert iter_statements(sql) == []
