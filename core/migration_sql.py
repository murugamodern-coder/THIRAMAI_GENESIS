"""
Split and apply PostgreSQL DDL from repository ``db/*.sql`` files (Alembic upgrades).

Uses sqlparse for statement boundaries.
"""

from __future__ import annotations

from pathlib import Path

import sqlparse
from alembic import op
import psycopg2.errors
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

_DUPLICATE_DDL_TYPES: tuple[type, ...] = (
    psycopg2.errors.DuplicateObject,
    psycopg2.errors.DuplicateTable,
    psycopg2.errors.DuplicateSchema,
    psycopg2.errors.DuplicateColumn,
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


# Order: orgs/core tables first (db_schema.sql), then identity (auth_rbac → users), then dependents.
# Life OS + project_staff_assignments were removed from db_schema.sql (they need users); see
# db/factory_os.sql and db/life_os.sql later in this tuple. Legacy db/schema.sql omitted (pre-V2.1 orgs).
SQL_BASELINE_FILES: tuple[str, ...] = (
    "db/db_schema.sql",
    "db/auth_rbac.sql",
    "db/approvals_table.sql",
    "db/notifications_alerts.sql",
    "db/learning_logs.sql",
    "db/system_audit_logs.sql",
    "db/bills_table.sql",
    "db/departments.sql",
    "db/invoices.sql",
    "db/inventory_gst_columns.sql",
    "db/inventory_hsn_code.sql",
    "db/idempotency_and_jobs.sql",
    "db/perf_indexes_phase2.sql",
    "db/factory_os.sql",
    "db/life_os.sql",
    "db/migrate_roles_add_org_id.sql",
)


def iter_statements(sql: str) -> list[str]:
    out: list[str] = []
    for stmt in sqlparse.split(sql):
        s = (stmt or "").strip()
        if not s:
            continue
        lines = [ln for ln in s.splitlines() if ln.strip() and not ln.strip().startswith("--")]
        if not lines:
            continue
        out.append(s)
    return out


def _pgcode_is_baseline_duplicate(code: str | None) -> bool:
    """PostgreSQL SQLSTATEs for 'already exists' — safe to skip when re-applying baseline DDL."""
    if not code:
        return False
    return code in frozenset(
        {
            "42710",  # duplicate_object (ENUM types, etc.)
            "42P07",  # duplicate_table / relation already exists (tables, indexes as relations)
            "42701",  # duplicate_column
            "42P06",  # duplicate_schema
        }
    )


def _is_baseline_duplicate_programming_error(exc: ProgrammingError) -> bool:
    e: BaseException | None = exc
    for _ in range(12):
        if e is None:
            break
        if isinstance(e, _DUPLICATE_DDL_TYPES):
            return True
        code = getattr(e, "pgcode", None)
        if _pgcode_is_baseline_duplicate(code):
            return True
        e = getattr(e, "orig", None)
    return False


def apply_sql_files(rel_paths: tuple[str, ...] | list[str]) -> None:
    """Apply DDL statements; skip duplicate-object errors (idempotent baseline)."""
    root = project_root()
    bind = op.get_bind()
    sp_counter = 0
    for rel in rel_paths:
        path = root / rel
        if not path.is_file():
            raise FileNotFoundError(f"Alembic baseline SQL missing: {path}")
        raw = path.read_text(encoding="utf-8")
        for statement in iter_statements(raw):
            sp = f"th_baseline_{sp_counter}"
            sp_counter += 1
            bind.execute(text(f"SAVEPOINT {sp}"))
            try:
                bind.execute(text(statement))
            except ProgrammingError as exc:
                bind.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
                if _is_baseline_duplicate_programming_error(exc):
                    continue
                raise
            except Exception:
                bind.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
                raise
            bind.execute(text(f"RELEASE SAVEPOINT {sp}"))
