"""
Production go-live gate for THIRAMAI GENESIS.

Verifies required environment variables, PostgreSQL + ``alembic_version`` head
(current head via ``core.migration_head.EXPECTED_ALEMBIC_REVISION``), Redis PING, and at least one live
worker heartbeat (``job_worker`` or ``alert_worker``).

Each check emits one structured JSON log line. On full success, prints a single plain-text
banner and exits 0; otherwise exits 1.

Usage (repo root, with the same env as production)::

    python scripts/go_live_checklist.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text  # noqa: E402

from core.database import get_database_url, normalize_database_url  # noqa: E402
from core.migration_head import EXPECTED_ALEMBIC_REVISION  # noqa: E402
from core.observability import ensure_thiramai_logging, log_structured  # noqa: E402
from services.worker_heartbeat import any_heartbeat_for_role, redis_ping_ok  # noqa: E402

_REQUIRED_ENV = ("DATABASE_URL", "REDIS_URL", "SECRET_KEY", "VAULT_PASSPHRASE")
_MIN_VAULT_PASSPHRASE_LEN = 8


def _check_env_vars() -> tuple[bool, str]:
    missing = [k for k in _REQUIRED_ENV if not (os.getenv(k) or "").strip()]
    if missing:
        return False, f"missing or empty: {', '.join(missing)}"
    vault = (os.getenv("VAULT_PASSPHRASE") or "").strip()
    if len(vault) < _MIN_VAULT_PASSPHRASE_LEN:
        return (
            False,
            f"VAULT_PASSPHRASE must be at least {_MIN_VAULT_PASSPHRASE_LEN} characters "
            "(matches server Fernet derivation in life_os_service)",
        )
    return True, "DATABASE_URL, REDIS_URL, SECRET_KEY, VAULT_PASSPHRASE set"


def _check_postgres_alembic() -> tuple[bool, str]:
    raw = get_database_url()
    if not raw:
        return False, "DATABASE_URL is not set"
    normalized = normalize_database_url(raw)
    if not normalized.split("://", 1)[0].startswith("postgresql"):
        return False, "DATABASE_URL must be a PostgreSQL URL for Alembic go-live"
    try:
        engine = create_engine(normalized, pool_pre_ping=True)
        with engine.connect() as conn:
            if conn.dialect.name != "postgresql":
                return False, f"connected dialect is {conn.dialect.name!r}; expected postgresql"
            conn.execute(text("SELECT 1"))
            try:
                rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
            except Exception as exc:
                return False, f"alembic_version not available: {type(exc).__name__}: {exc}"
            if not rows:
                return False, "alembic_version has no rows — run: alembic upgrade head"
            versions = {str(r[0]).strip() for r in rows if r and r[0] is not None}
            if len(versions) != 1:
                return False, f"expected single Alembic head; got {sorted(versions)}"
            rev = next(iter(versions))
            if rev != _ALEMBIC_HEAD:
                return False, f"alembic version is {rev!r}; required {_ALEMBIC_HEAD!r}"
    except Exception as exc:
        return False, f"database error: {type(exc).__name__}: {exc}"
    return True, f"PostgreSQL OK; alembic_version = {_ALEMBIC_HEAD}"


def _check_redis() -> tuple[bool, str]:
    ok, msg = redis_ping_ok()
    if ok:
        return True, msg
    return False, msg


def _check_workers() -> tuple[bool, str]:
    job = any_heartbeat_for_role("job_worker")
    alert = any_heartbeat_for_role("alert_worker")
    if job or alert:
        parts = []
        if job:
            parts.append("job_worker")
        if alert:
            parts.append("alert_worker")
        return True, f"active heartbeat: {', '.join(parts)}"
    return (
        False,
        "no active Redis heartbeat for job_worker or alert_worker "
        "(start workers.run_worker and/or workers.alert_system)",
    )


def main() -> None:
    ensure_thiramai_logging()
    log_structured("go_live_checklist.start", expected_alembic=EXPECTED_ALEMBIC_REVISION)

    checks: list[tuple[str, tuple[bool, str]]] = [
        ("env_vars", _check_env_vars()),
        ("postgresql_alembic", _check_postgres_alembic()),
        ("redis_ping", _check_redis()),
        ("worker_heartbeat", _check_workers()),
    ]

    all_ok = True
    for name, (ok, detail) in checks:
        log_structured(
            "go_live_checklist.check",
            check=name,
            ok=ok,
            detail=detail,
        )
        if not ok:
            all_ok = False

    if not all_ok:
        log_structured("go_live_checklist.result", ok=False)
        sys.exit(1)

    log_structured("go_live_checklist.result", ok=True, detail="all checks passed")
    print("THIRAMAI SYSTEM READY FOR GO-LIVE")
    sys.exit(0)


if __name__ == "__main__":
    main()
