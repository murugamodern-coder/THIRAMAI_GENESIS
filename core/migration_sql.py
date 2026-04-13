"""
Split and apply PostgreSQL DDL from repository ``db/*.sql`` files (Alembic upgrades).

Uses sqlparse for statement boundaries.
"""

from __future__ import annotations

import re
from pathlib import Path

import sqlparse
from alembic import op
import psycopg2.errors
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

# Baseline identity: `users` (and roles) are defined here; must run after org/core DDL in db_schema.sql.
_BASELINE_ORG_CORE = "db/db_schema.sql"
_BASELINE_IDENTITY = "db/auth_rbac.sql"

# FK target ``users`` (word boundary avoids matching ``user_session``-style names).
_RE_REFERENCES_USERS = re.compile(r"REFERENCES\s+users\b", re.IGNORECASE)
# ``migrate_roles_add_org_id.sql`` alters ``roles`` created in auth_rbac — must run after identity.
_RE_ALTER_TABLE_ROLES = re.compile(r"ALTER\s+TABLE\s+roles\b", re.IGNORECASE)

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
    # Phase 2 enterprise inventory / PO / payments (needs organizations, invoices, users)
    "db/phase2_core_business.sql",
    "db/inventory_gst_columns.sql",
    "db/inventory_hsn_code.sql",
    "db/idempotency_and_jobs.sql",
    "db/perf_indexes_phase2.sql",
    "db/factory_os.sql",
    "db/life_os.sql",
    "db/migrate_roles_add_org_id.sql",
)


def _file_requires_post_identity(root: Path, rel: str) -> bool:
    """True if DDL must run after ``auth_rbac.sql`` (users / roles from identity)."""
    path = root / rel
    if not path.is_file():
        return False
    raw = path.read_text(encoding="utf-8")
    if _RE_REFERENCES_USERS.search(raw):
        return True
    if _RE_ALTER_TABLE_ROLES.search(raw):
        return True
    return False


def normalize_baseline_sql_paths(paths: tuple[str, ...] | list[str]) -> list[str]:
    """
    Dedupe (first occurrence wins) and enforce **strict** baseline phases:

    1. **CORE** — ``db/db_schema.sql`` (organizations + tables without ``users`` FK).
    2. **PRE_IDENTITY** — other files that do not reference ``users`` and do not ``ALTER TABLE roles``.
    3. **IDENTITY** — ``db/auth_rbac.sql`` (creates ``roles``, ``users``, …).
    4. **POST_IDENTITY** — files that ``REFERENCES users`` or alter ``roles`` (Life OS, factory staff,
       approvals, ``migrate_roles_add_org_id.sql``, …).

    Relative order within PRE and POST matches the order of first appearance in ``paths``.
    This prevents ``relation users does not exist`` even when ``SQL_BASELINE_FILES`` is shuffled.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for p in paths:
        if p not in seen:
            unique.append(p)
            seen.add(p)
    root = project_root()
    rest = [p for p in unique if p not in (_BASELINE_ORG_CORE, _BASELINE_IDENTITY)]
    pre: list[str] = []
    post: list[str] = []
    for rel in rest:
        if _file_requires_post_identity(root, rel):
            post.append(rel)
        else:
            pre.append(rel)
    out: list[str] = []
    if _BASELINE_ORG_CORE in seen:
        out.append(_BASELINE_ORG_CORE)
    out.extend(pre)
    if _BASELINE_IDENTITY in seen:
        out.append(_BASELINE_IDENTITY)
    out.extend(post)
    return out


def _users_table_exists(bind) -> bool:
    row = bind.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'users')"
        )
    ).scalar()
    return bool(row)


def _statement_references_users(statement: str) -> bool:
    return bool(_RE_REFERENCES_USERS.search(statement))


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


def _execute_one_statement(
    *,
    bind,
    statement: str,
    sp_name: str,
) -> None:
    bind.execute(text(f"SAVEPOINT {sp_name}"))
    try:
        bind.execute(text(statement))
    except ProgrammingError as exc:
        bind.execute(text(f"ROLLBACK TO SAVEPOINT {sp_name}"))
        if _is_baseline_duplicate_programming_error(exc):
            return
        raise
    except Exception:
        bind.execute(text(f"ROLLBACK TO SAVEPOINT {sp_name}"))
        raise
    bind.execute(text(f"RELEASE SAVEPOINT {sp_name}"))


def _apply_statements_from_file(
    *,
    root: Path,
    rel: str,
    bind,
    sp_counter: int,
) -> int:
    path = root / rel
    if not path.is_file():
        raise FileNotFoundError(f"Alembic baseline SQL missing: {path}")
    raw = path.read_text(encoding="utf-8")
    statements = iter_statements(raw)
    # Files that reference ``users`` (or alter ``roles``) also often contain follow-on DDL
    # (e.g. ``CREATE INDEX ON approvals``) that must run *after* ``users`` exists but does not
    # literally include the substring ``REFERENCES users``. Run the whole file in order post-identity.
    if _file_requires_post_identity(root, rel):
        if not _users_table_exists(bind):
            raise RuntimeError(
                f"Baseline file {rel!r} requires `users` but table is missing — "
                f"ensure {_BASELINE_IDENTITY!r} ran earlier (check normalize_baseline_sql_paths)."
            )
        for statement in statements:
            sp = f"th_baseline_{sp_counter}"
            sp_counter += 1
            _execute_one_statement(bind=bind, statement=statement, sp_name=sp)
        return sp_counter

    without_users: list[str] = []
    with_users: list[str] = []
    for statement in statements:
        if _statement_references_users(statement):
            with_users.append(statement)
        else:
            without_users.append(statement)
    for statement in without_users:
        sp = f"th_baseline_{sp_counter}"
        sp_counter += 1
        _execute_one_statement(bind=bind, statement=statement, sp_name=sp)
    for statement in with_users:
        if not _users_table_exists(bind):
            raise RuntimeError(
                f"Baseline statement in {rel!r} references `users` but table is missing — "
                f"ensure {_BASELINE_IDENTITY!r} ran earlier (check normalize_baseline_sql_paths)."
            )
        sp = f"th_baseline_{sp_counter}"
        sp_counter += 1
        _execute_one_statement(bind=bind, statement=statement, sp_name=sp)
    return sp_counter


def apply_sql_files(rel_paths: tuple[str, ...] | list[str]) -> None:
    """Apply DDL statements; skip duplicate-object errors (idempotent baseline)."""
    root = project_root()
    bind = op.get_bind()
    paths = normalize_baseline_sql_paths(rel_paths)
    if _BASELINE_IDENTITY in paths and _BASELINE_ORG_CORE not in paths:
        raise RuntimeError(
            f"Baseline requires {_BASELINE_ORG_CORE!r} (organizations, core tables) before "
            f"{_BASELINE_IDENTITY!r} (users / RBAC)."
        )
    sp_counter = 0
    for rel in paths:
        sp_counter = _apply_statements_from_file(
            root=root, rel=rel, bind=bind, sp_counter=sp_counter
        )
