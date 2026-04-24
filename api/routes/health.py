"""Unified liveness / readiness for orchestration (Kubernetes, Nginx, probes)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import text

from core.database import get_engine
from core.http_metrics import snapshot as http_metrics_snapshot
from core.migration_head import EXPECTED_ALEMBIC_REVISION
from core.schema_mode import allow_create_all_auto
from core.stability.circuit_breaker import export_breaker_snapshots
from services.stock_market_data_service import get_live_price
from services.worker_heartbeat import expected_worker_roles_from_env, redis_ping_ok, workers_ready_detail

router = APIRouter(tags=["System"])

REQUEST_COUNT = Counter(
    "thiramai_requests_total",
    "Total requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "thiramai_request_duration_seconds",
    "Request latency",
    ["endpoint"],
)

WORKER_JOB_DURATION = Histogram(
    "thiramai_worker_job_duration_seconds",
    "Worker job processing time",
    ["job_type"],
)

ACTIVE_ORGS = Gauge(
    "thiramai_active_organizations",
    "Number of active organizations",
)


def _execution_runtime_metrics(window_hours: int = 24) -> dict:
    engine = get_engine()
    if engine is None:
        return {"ok": False, "reason": "database_unavailable"}
    since = datetime.now(timezone.utc) - timedelta(hours=max(1, int(window_hours)))
    try:
        with engine.connect() as conn:
            total = int(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM action_execution_runs WHERE created_at >= :since"
                    ),
                    {"since": since},
                ).scalar()
                or 0
            )
            success = int(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM action_execution_runs WHERE created_at >= :since AND status = 'completed'"
                    ),
                    {"since": since},
                ).scalar()
                or 0
            )
            failed = int(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM action_execution_runs WHERE created_at >= :since AND status = 'failed'"
                    ),
                    {"since": since},
                ).scalar()
                or 0
            )
            retrying = int(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM action_execution_runs WHERE created_at >= :since AND status = 'retrying'"
                    ),
                    {"since": since},
                ).scalar()
                or 0
            )
            avg_exec_seconds = float(
                conn.execute(
                    text(
                        "SELECT COALESCE(AVG(EXTRACT(EPOCH FROM (updated_at - created_at))), 0) "
                        "FROM action_execution_runs WHERE created_at >= :since"
                    ),
                    {"since": since},
                ).scalar()
                or 0.0
            )
            backlog = int(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM action_execution_runs "
                        "WHERE status IN ('planned', 'awaiting_confirmation', 'running')"
                    )
                ).scalar()
                or 0
            )
            stuck_running = int(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM action_execution_runs "
                        "WHERE status = 'running' AND updated_at < :stuck_cutoff"
                    ),
                    {"stuck_cutoff": datetime.now(timezone.utc) - timedelta(minutes=20)},
                ).scalar()
                or 0
            )
        success_rate = (float(success) / float(total)) if total > 0 else 0.0
        failure_rate = (float(failed) / float(total)) if total > 0 else 0.0
        retry_rate = (float(retrying) / float(total)) if total > 0 else 0.0
        alerts: list[dict] = []
        if failure_rate >= 0.30:
            alerts.append({"level": "warning", "type": "high_failure_rate", "value": round(failure_rate, 4)})
        if retry_rate >= 0.25:
            alerts.append({"level": "warning", "type": "high_retry_rate", "value": round(retry_rate, 4)})
        if backlog >= 100 or stuck_running > 0:
            alerts.append({"level": "critical", "type": "execution_backlog_or_stuck_runs", "backlog": backlog, "stuck_running": stuck_running})
        return {
            "ok": True,
            "window_hours": int(window_hours),
            "total_runs": total,
            "success_rate": round(success_rate, 4),
            "failure_rate": round(failure_rate, 4),
            "retry_rate": round(retry_rate, 4),
            "avg_execution_time_seconds": round(avg_exec_seconds, 3),
            "execution_backlog": backlog,
            "stuck_running_count": stuck_running,
            "alerts": alerts,
        }
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def observe_request_metric(method: str, endpoint: str, status: int, start_ts: float) -> None:
    """Helper for route/middleware integrations to track request count and latency."""
    REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=str(status)).inc()
    REQUEST_LATENCY.labels(endpoint=endpoint).observe(max(time.time() - start_ts, 0.0))


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
        "metrics": "/health/metrics",
        "stocks": "/health/stocks",
    }


@router.get("/health/live", summary="Liveness — process is up")
def health_live() -> dict:
    return {"status": "alive", "service": "thiramai-genesis"}


@router.get("/health/metrics", summary="In-process HTTP counters (since process start)")
def health_metrics() -> dict:
    """``requests_total`` and ``errors_total`` (5xx responses) from CorrelationId middleware."""
    return {"service": "thiramai-genesis", **http_metrics_snapshot()}


@router.get("/health/stocks", summary="Optional quote probe (yfinance / nsepython fallback)")
def health_stocks() -> dict:
    """
    Non-authenticated smoke check for market data stack (best-effort).

    Uses a liquid NSE symbol; failures return ``ok: false`` without failing liveness.
    """
    q = get_live_price("RELIANCE", exchange_suffix="NS")
    return {
        "service": "thiramai-genesis",
        "ok": bool(q.get("ok")),
        "symbol": q.get("symbol"),
        "detail": "quote ok" if q.get("ok") else (q.get("error") or "quote failed"),
    }


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

    checks["today_brief"] = {
        "ok": True,
        "detail": "Command Center /personal and GET /personal/today expose the daily brief when authenticated.",
    }

    try:
        from thiramai.runtime import goal_jobs

        gs = goal_jobs.readiness_snapshot()
        checks["thiramai_goal_store"] = gs
        if gs.get("job_sqlite_enabled"):
            ok_all = ok_all and bool(gs.get("sqlite", {}).get("ok"))
    except Exception as exc:
        checks["thiramai_goal_store"] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
        ok_all = False

    cb_snaps = export_breaker_snapshots()
    checks["circuit_breakers"] = {
        "open_count": sum(1 for b in cb_snaps if str(b.get("state")) == "open"),
        "items": cb_snaps,
    }
    checks["execution_runtime"] = _execution_runtime_metrics(window_hours=24)
    if checks["execution_runtime"].get("ok"):
        rt = checks["execution_runtime"]
        if float(rt.get("failure_rate") or 0.0) >= 0.30 or int(rt.get("stuck_running_count") or 0) > 0:
            ok_all = False

    body = {
        "status": "ready" if ok_all else "not_ready",
        "checks": checks,
        "expected_workers_env": expected_worker_roles_from_env(),
        "metrics": http_metrics_snapshot(),
    }
    return JSONResponse(status_code=200 if ok_all else 503, content=body)


@router.get("/health/system", summary="Execution health and backlog")
def health_system() -> JSONResponse:
    payload = _execution_runtime_metrics(window_hours=24)
    ok = bool(payload.get("ok")) and int(payload.get("stuck_running_count") or 0) == 0
    return JSONResponse(status_code=200 if ok else 503, content=payload)
