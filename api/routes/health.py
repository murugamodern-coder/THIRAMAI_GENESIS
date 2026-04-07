"""Unified liveness / readiness for orchestration (Kubernetes, Nginx, probes)."""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from core.database import get_engine
from core.migration_head import EXPECTED_ALEMBIC_REVISION
from core.schema_mode import allow_create_all_auto
from services.worker_heartbeat import expected_worker_roles_from_env, redis_ping_ok, workers_ready_detail

router = APIRouter(tags=["System"])


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _alembic_status() -> dict:
    if (os.getenv("THIRAMAI_SKIP_ALEMBIC_CHECK") or "").strip() == "1":
        return {"ok": True, "detail": "skipped (THIRAMAI_SKIP_ALEMBIC_CHECK=1)", "revision": None}
    engine = get_engine()
    if engine is None:
        return {"ok": False, "detail": "DATABASE_URL not configured", "revision": None}
    if engine.dialect.name != "postgresql":
        return {
            "ok": True,
            "detail": "non-postgresql dialect — alembic baseline skipped",
            "revision": None,
        }
    try:
        with engine.connect() as conn:
            if not conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar():
                return {
                    "ok": False,
                    "detail": "alembic_version missing — run: alembic upgrade head",
                    "revision": None,
                }
            rev = conn.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1")).scalar()
        if rev != EXPECTED_ALEMBIC_REVISION:
            return {
                "ok": False,
                "detail": f"revision {rev!r} != expected {EXPECTED_ALEMBIC_REVISION!r}",
                "revision": rev,
            }
        return {"ok": True, "detail": "at expected head", "revision": rev}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}", "revision": None}


@router.get("/health", summary="Discovery — links to liveness and readiness probes")
def health_index() -> dict:
    """Orchestrator-friendly entry (Render, Railway, k8s) — use ``/health/live`` or ``/health/ready`` for probes."""
    return {
        "service": "thiramai-genesis",
        "live": "/health/live",
        "ready": "/health/ready",
    }


@router.get("/health/live", summary="Liveness — process is up")
def health_live() -> dict:
    return {"status": "alive", "service": "thiramai-genesis"}


@router.get("/health/ready", summary="Readiness — DB, optional Redis, Alembic, optional worker heartbeats")
def health_ready() -> JSONResponse:
    """
    Returns **200** when dependencies configured in env are satisfied.

    - **PostgreSQL**: ``SELECT 1``
    - **Alembic**: when dialect is PostgreSQL, ``alembic_version`` must match ``EXPECTED_ALEMBIC_REVISION``
    - **Redis**: if ``REDIS_URL`` set, must PING
    - **Workers**: if ``THIRAMAI_HEALTH_EXPECT_WORKERS`` lists roles (e.g. ``job_worker,alert_worker``), each must have a fresh Redis heartbeat key
    """
    checks: dict = {}
    ok_all = True

    engine = get_engine()
    if engine is None:
        checks["database"] = {"ok": False, "detail": "DATABASE_URL not set"}
        ok_all = False
    else:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["database"] = {"ok": True, "detail": "SELECT 1 ok"}
        except Exception as exc:
            checks["database"] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
            ok_all = False

    if (os.getenv("REDIS_URL") or "").strip():
        r_ok, r_msg = redis_ping_ok()
        checks["redis"] = {"ok": r_ok, "detail": r_msg}
        ok_all = ok_all and r_ok
    else:
        checks["redis"] = {"ok": True, "detail": "skipped (REDIS_URL unset)"}

    if engine is not None and engine.dialect.name == "postgresql":
        alembic = _alembic_status()
        checks["alembic"] = alembic
        ok_all = ok_all and alembic.get("ok", False)
    else:
        checks["alembic"] = {"ok": True, "detail": "skipped (non-PostgreSQL or no engine)"}

    wd = workers_ready_detail()
    checks["workers"] = wd
    if wd.get("configured"):
        ok_all = ok_all and bool(wd.get("ok"))

    groq_ok = bool((os.getenv("GROQ_API_KEY") or "").strip())
    tav_ok = bool((os.getenv("TAVILY_API_KEY") or "").strip())
    checks["ai"] = {
        "ok": groq_ok and tav_ok,
        "groq_configured": groq_ok,
        "tavily_configured": tav_ok,
        "detail": (
            "GROQ_API_KEY and TAVILY_API_KEY present (brain/chat available)"
            if groq_ok and tav_ok
            else "Missing GROQ_API_KEY or TAVILY_API_KEY — /chat returns 503 until set"
        ),
    }
    if _truthy("THIRAMAI_HEALTH_REQUIRE_AI"):
        ok_all = ok_all and groq_ok and tav_ok

    checks["schema_mode"] = {
        "create_all_auto_allowed": allow_create_all_auto(),
        "hint": "production should set ENV=production or THIRAMAI_DISABLE_CREATE_ALL=1 and use Alembic only",
    }

    body = {
        "status": "ready" if ok_all else "not_ready",
        "checks": checks,
        "expected_workers_env": expected_worker_roles_from_env(),
    }
    return JSONResponse(status_code=200 if ok_all else 503, content=body)
