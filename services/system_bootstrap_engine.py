"""System bootstrap and runtime health monitoring for live deployment."""

from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import ExecutionAuditLog, UserOrganizationMembership
from core.production_safety import assert_safe_production_config
from services.autonomous_operations_engine import run_multi_org_daily_cycles
from services.autonomy_contract_engine import set_autonomy_state
from services.governance_engine import list_execution_logs, set_kill_switch
from services.money_loop_engine import upsert_money_loop_config


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _env_readiness() -> dict[str, Any]:
    required = {
        "DATABASE_URL": bool((os.getenv("DATABASE_URL") or "").strip()),
        "JWT_SECRET_KEY": bool((os.getenv("JWT_SECRET_KEY") or os.getenv("JWT_SECRET") or "").strip()),
    }
    return {
        "ok": all(required.values()),
        "required": required,
    }


def _migration_readiness() -> dict[str, Any]:
    try:
        current = subprocess.run(["alembic", "current"], capture_output=True, text=True, timeout=20, shell=False)
        heads = subprocess.run(["alembic", "heads"], capture_output=True, text=True, timeout=20, shell=False)
        cur_out = (current.stdout or current.stderr or "").strip()
        head_out = (heads.stdout or heads.stderr or "").strip()
        ok = current.returncode == 0 and heads.returncode == 0 and bool(cur_out) and bool(head_out)
        return {
            "ok": bool(ok),
            "current": cur_out[:500],
            "heads": head_out[:500],
            "current_rc": current.returncode,
            "heads_rc": heads.returncode,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def bootstrap_system(
    *,
    app,
    user_id: int,
    organization_id: int,
) -> dict[str, Any]:
    prod_checks = {"ok": True, "errors": []}
    try:
        assert_safe_production_config()
    except Exception as exc:
        prod_checks = {"ok": False, "errors": [str(exc)]}
    env_checks = _env_readiness()
    migration_checks = _migration_readiness()

    autonomy = set_autonomy_state(
        user_id=int(user_id),
        organization_id=int(organization_id),
        mode="recommend",
        approval_required_for_high_impact=True,
        notes="System bootstrap safe mode",
    )
    loop_cfg = upsert_money_loop_config(
        user_id=int(user_id),
        enabled=True,
        auto_execute=False,
        risk_level="medium",
        max_daily_capital=25000.0,
        max_parallel_missions=1,
        optimizer_enabled=True,
    )
    set_kill_switch(int(user_id), enabled=False, reason="system bootstrap start")

    scheduler_status: dict[str, Any] = {"started": False}
    sch = getattr(app.state, "scheduler", None)
    if sch is None:
        from services.scheduler import ThiramaiScheduler

        sch = ThiramaiScheduler(app)
        await sch.start()
        app.state.scheduler = sch
        scheduler_status = {"started": True, "created": True}
    else:
        if not bool(getattr(sch, "running", False)):
            await sch.start()
            scheduler_status = {"started": True, "created": False, "restarted": True}
        else:
            scheduler_status = {"started": True, "created": False, "already_running": True}

    app.state.system_started_at = getattr(app.state, "system_started_at", _now())
    daily = await asyncio.to_thread(run_multi_org_daily_cycles, int(user_id))
    return {
        "ok": bool(prod_checks.get("ok") and env_checks.get("ok")),
        "production_readiness": prod_checks,
        "environment_readiness": env_checks,
        "migration_readiness": migration_checks,
        "autonomy": autonomy,
        "money_loop": loop_cfg or {},
        "scheduler": scheduler_status,
        "daily_cycle": daily,
        "started_at": app.state.system_started_at.isoformat() if getattr(app.state, "system_started_at", None) else None,
    }


def runtime_health(*, app, user_id: int) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "Database unavailable"}
    started = getattr(app.state, "system_started_at", None)
    now = _now()
    uptime_sec = int((now - started).total_seconds()) if started else 0
    with factory() as session:
        org_count = (
            session.execute(
                select(UserOrganizationMembership.organization_id)
                .where(UserOrganizationMembership.user_id == int(user_id), UserOrganizationMembership.is_active.is_(True))
                .distinct()
            )
            .scalars()
            .all()
        )
        since = now - timedelta(hours=24)
        rows = (
            session.execute(
                select(ExecutionAuditLog)
                .where(ExecutionAuditLog.user_id == int(user_id), ExecutionAuditLog.created_at >= since)
                .order_by(ExecutionAuditLog.created_at.desc(), ExecutionAuditLog.id.desc())
                .limit(200)
            )
            .scalars()
            .all()
        )
    running_cycles = sum(
        1
        for r in rows
        if str(r.action_type or "") in {"continuous_thinking_execute", "money_loop_execute"} and str(r.status or "") == "success"
    )
    last_status = str(rows[0].status or "unknown") if rows else "unknown"
    scheduler_running = bool(getattr(getattr(app.state, "scheduler", None), "running", False))
    return {
        "ok": True,
        "live_state": "LIVE" if scheduler_running else "STOPPED",
        "uptime_seconds": uptime_sec,
        "active_org_count": len(org_count),
        "running_cycles_24h": running_cycles,
        "last_execution_status": last_status,
    }
