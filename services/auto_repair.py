"""
Autonomous DB self-heal: Alembic migrate, PostgreSQL ``organizations`` sequence realign, Uvicorn reload hint.

Invoked from the dashboard **Run** console (intent ``run_auto_repair``) or ``python -m services.auto_repair``.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
_LOG = logging.getLogger(__name__)


def organization_integrity_failed(*, profile: str = "development") -> tuple[bool, str]:
    """
    True when SRE ``organization_integrity`` is not OK, or a schema/programming-class DB error is likely.
    """
    prof = profile if profile in ("development", "production") else "development"
    try:
        from services.sre_health_report import build_sre_health_report

        report = build_sre_health_report(profile=prof, write_reflection=False)
        chk = (report.get("checks") or {}).get("organization_integrity") or {}
        if isinstance(chk, dict):
            if bool(chk.get("ok", True)):
                return False, ""
            return True, str(chk.get("detail") or "organization_integrity failed")[:400]
    except (ProgrammingError, OperationalError) as exc:
        return True, f"{type(exc).__name__}: {str(exc)[:360]}"
    except Exception as exc:
        et = type(exc).__name__
        if et == "ProgrammingError" or "ProgrammingError" in et:
            return True, f"{et}: {str(exc)[:360]}"
        low = str(exc).lower()
        if "no such table" in low or "undefinedtable" in low or "does not exist" in low:
            return True, f"{et}: {str(exc)[:360]}"

    try:
        from core.database import get_session_factory
        from core.db.models import Organization

        factory = get_session_factory()
        if factory is None:
            return False, ""
        with factory() as session:
            session.execute(select(Organization.id).limit(1))
    except ProgrammingError as exc:
        return True, f"ProgrammingError: {str(exc)[:360]}"
    except OperationalError as exc:
        low = str(exc).lower()
        if "no such table" in low or "does not exist" in low:
            return True, f"OperationalError: {str(exc)[:360]}"
    except Exception:
        pass

    return False, ""


def run_alembic_upgrade_head(*, timeout_sec: int = 600) -> dict[str, Any]:
    """Run ``alembic upgrade head`` from repository root."""
    alembic_ini = ROOT / "alembic.ini"
    if not alembic_ini.is_file():
        return {"ok": False, "step": "alembic", "error": "alembic.ini not found", "stdout": "", "stderr": ""}
    cmd = [sys.executable, "-m", "alembic", "-c", str(alembic_ini), "upgrade", "head"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=int(timeout_sec),
            env=os.environ.copy(),
        )
        return {
            "ok": proc.returncode == 0,
            "step": "alembic",
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-8000:],
            "stderr": (proc.stderr or "")[-8000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "step": "alembic", "error": "timeout", "stdout": "", "stderr": ""}
    except Exception as exc:
        return {"ok": False, "step": "alembic", "error": f"{type(exc).__name__}: {exc}", "stdout": "", "stderr": ""}


def reset_organizations_id_sequence_safe(session: Session | None = None) -> dict[str, Any]:
    """
    Realign PostgreSQL sequence for ``organizations.id``; no-op on SQLite / missing sequence.
    """
    from core.db.provisioning import sync_organizations_id_sequence

    close_session = False
    if session is None:
        from core.database import get_session_factory

        factory = get_session_factory()
        if factory is None:
            return {"ok": True, "step": "sequence", "detail": "skipped_no_database_url"}
        session = factory()
        close_session = True
    try:
        sync_organizations_id_sequence(session)
        if close_session:
            session.commit()
        return {"ok": True, "step": "sequence", "detail": "sync_organizations_id_sequence executed"}
    except Exception as exc:
        _LOG.warning("reset_organizations_id_sequence_safe: %s", exc)
        return {"ok": True, "step": "sequence", "detail": f"non_fatal_{type(exc).__name__}"}
    finally:
        if close_session and session is not None:
            session.close()


def restart_uvicorn_best_effort() -> dict[str, Any]:
    """
    Try to refresh the running app without requiring manual intervention.

    1. If ``THIRAMAI_UVICORN_RELOAD`` is enabled, touch ``THIRAMAI_UVICORN_RELOAD_TOUCH`` (default ``main.py``)
       so a ``uvicorn --reload`` process picks up changes.
    2. Else if ``THIRAMAI_UVICORN_RESTART_CMD`` is set, spawn that command detached (operator may need to stop
       the old process if the port is still held).
    """
    reload_on = (os.getenv("THIRAMAI_UVICORN_RELOAD") or "").strip().lower() in ("1", "true", "yes", "on")
    if reload_on:
        rel = (os.getenv("THIRAMAI_UVICORN_RELOAD_TOUCH") or "main.py").strip() or "main.py"
        path = ROOT / rel
        try:
            if path.is_file():
                path.touch(exist_ok=True)
            else:
                (ROOT / "main.py").touch(exist_ok=True)
            return {"ok": True, "step": "restart", "detail": f"touched_{path.name}_for_reload"}
        except OSError as exc:
            return {"ok": False, "step": "restart", "detail": str(exc)}

    cmd_line = (os.getenv("THIRAMAI_UVICORN_RESTART_CMD") or "").strip()
    if not cmd_line:
        return {
            "ok": False,
            "step": "restart",
            "detail": "skipped_set_THIRAMAI_UVICORN_RELOAD_or_THIRAMAI_UVICORN_RESTART_CMD",
        }
    try:
        posix = os.name != "nt"
        args = shlex.split(cmd_line, posix=posix)
        kwargs: dict[str, Any] = {
            "cwd": str(ROOT),
            "env": os.environ.copy(),
        }
        if os.name == "nt":
            # DETACHED_PROCESS so the child survives parent teardown if operator stops the old server later.
            kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0)
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(args, **kwargs)
        return {"ok": True, "step": "restart", "detail": "spawned_THIRAMAI_UVICORN_RESTART_CMD"}
    except Exception as exc:
        return {"ok": False, "step": "restart", "detail": f"{type(exc).__name__}: {exc}"}


def run_auto_repair(
    *,
    profile: str = "development",
    force: bool = False,
    target: str | None = None,
    organization_id: int | None = None,
) -> dict[str, Any]:
    """
    When ``force`` is False, run repair steps only if ``organization_integrity_failed`` or a
    programming/schema error is detected. When ``force`` is True (dashboard **Run**), always execute
    Alembic upgrade, sequence sync, and best-effort restart.

    ``target=inventory_sync`` (optional ``--target inventory_sync``): tenant inventory corrections only
    (requires ``organization_id``); skips Alembic/sequence/restart.
    """
    prof = profile if profile in ("development", "production") else "development"
    tgt = (target or "").strip().lower().replace("-", "_")
    if tgt == "inventory_sync":
        oid = int(organization_id) if organization_id is not None else 0
        if oid <= 0:
            return {
                "ok": False,
                "profile": prof,
                "forced": bool(force),
                "target": "inventory_sync",
                "trigger": None,
                "steps": [
                    {
                        "step": "inventory_sync",
                        "ok": False,
                        "error": "organization_id_required",
                    }
                ],
            }
        from services.inventory_integrity_audit import apply_inventory_integrity_corrections

        sync_res = apply_inventory_integrity_corrections(oid)
        return {
            "ok": bool(sync_res.get("ok")),
            "profile": prof,
            "forced": bool(force),
            "target": "inventory_sync",
            "organization_id": oid,
            "trigger": "inventory_sync",
            "steps": [{"step": "inventory_sync", **sync_res}],
        }

    out: dict[str, Any] = {
        "ok": True,
        "profile": prof,
        "forced": bool(force),
        "trigger": None,
        "steps": [],
    }

    bad, reason = organization_integrity_failed(profile=prof)
    out["integrity_failed"] = bad
    out["integrity_detail"] = reason or None

    if not force and not bad:
        out["steps"].append({"step": "gate", "ok": True, "detail": "no_repair_needed"})
        return out

    out["trigger"] = "forced" if force else "integrity_or_schema_error"

    from core.database import reset_engine_cache

    alembic_res = run_alembic_upgrade_head()
    out["steps"].append(alembic_res)
    if not alembic_res.get("ok"):
        out["ok"] = False

    reset_engine_cache()
    seq_res = reset_organizations_id_sequence_safe()
    out["steps"].append(seq_res)

    restart_res = restart_uvicorn_best_effort()
    out["steps"].append(restart_res)
    out["restart"] = restart_res

    return out


def main() -> None:
    """CLI: ``python -m services.auto_repair`` — always runs full repair pipeline."""
    res = run_auto_repair(profile="development", force=True)
    print(res)
    sys.exit(0 if res.get("ok") else 1)


if __name__ == "__main__":
    main()
