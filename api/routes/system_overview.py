"""War-room system overview and decision traces."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from api.dependencies import CurrentUser, require_permission
from core.database import get_session_factory
from core.db.models import AutomationRule, ExecutionAuditLog, Mission
from services.governance_engine import list_execution_logs
from services.money_loop_engine import money_loop_status
from services.autonomy_contract_engine import autonomy_heartbeat
from services.goal_engine import goal_progress_snapshot
from services.world_model_engine import get_world_model
from services.multi_org_control_engine import shared_intelligence_context
from services.revenue_engine import revenue_snapshot

router = APIRouter(tags=["System Overview"])


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


@router.get("/system/overview")
async def get_system_overview(
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "trade_stock", "run_research")),
) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    loop = money_loop_status(int(user.id))
    logs = list_execution_logs(int(user.id), limit=25)
    items = logs.get("items") or []
    recent = []
    for row in items[:12]:
        recent.append(
            {
                "id": row.get("id"),
                "execution_id": row.get("execution_id") or f"audit_{row.get('id')}",
                "action_type": row.get("action_type"),
                "source": row.get("source"),
                "status": row.get("status"),
                "reasoning_summary": row.get("reasoning_summary") or row.get("why_action_taken") or "No reasoning captured",
                "data_influenced": row.get("data_influenced_json") or row.get("payload_json") or {},
                "created_at": row.get("created_at"),
            }
        )

    with factory() as session:
        missions = (
            session.execute(
                select(Mission).where(
                    Mission.user_id == int(user.id),
                    Mission.status.in_(["planned", "running"]),
                )
            )
            .scalars()
            .all()
        )
        active_missions = [
            {"id": int(m.id), "title": str(m.title or ""), "status": str(m.status or "")}
            for m in missions
        ]
        active_automations = (
            session.execute(
                select(AutomationRule).where(
                    AutomationRule.user_id == int(user.id),
                    AutomationRule.enabled.is_(True),
                )
            )
            .scalars()
            .all()
        )

    system_status = "PAUSED" if not bool((loop.get("config") or {}).get("enabled")) else "RUNNING"
    if (loop.get("failure_streak") or 0) >= 5:
        system_status = "PAUSED"

    return {
        "ok": True,
        "system_status": system_status,
        "active_missions": active_missions,
        "active_automations": len(active_automations),
        "money_loop_status": loop.get("config") or {},
        "today_profit_loss": loop.get("today_profit", 0),
        "risk_exposure": loop.get("risk_exposure", 0),
        "autonomy": autonomy_heartbeat(int(user.id)),
        "goal_progress": goal_progress_snapshot(int(user.id), "week"),
        "world_model": get_world_model(int(user.id)),
        "multi_org": shared_intelligence_context(int(user.id)),
        "revenue": revenue_snapshot(int(user.id), 24 * 7),
        "recent_decisions": recent,
    }


@router.get("/system/decision-trace/{execution_id}")
async def get_decision_trace(
    execution_id: str,
    user: CurrentUser = Depends(require_permission("manage_business", "build_apps", "trade_stock", "run_research")),
) -> dict[str, Any]:
    factory = _session_factory_or_none()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    eid = str(execution_id or "").strip()
    if not eid:
        raise HTTPException(status_code=400, detail="execution_id required")
    with factory() as session:
        rows = (
            session.execute(
                select(ExecutionAuditLog)
                .where(ExecutionAuditLog.user_id == int(user.id), ExecutionAuditLog.execution_id == eid)
                .order_by(ExecutionAuditLog.created_at.asc(), ExecutionAuditLog.id.asc())
            )
            .scalars()
            .all()
        )
    if not rows:
        # fallback to audit id style
        if eid.startswith("audit_"):
            try:
                aid = int(eid.split("_", 1)[1])
            except Exception:
                aid = 0
            if aid > 0:
                logs = list_execution_logs(int(user.id), limit=100).get("items") or []
                row = next((x for x in logs if int(x.get("id") or 0) == aid), None)
                if row:
                    return {
                        "ok": True,
                        "execution_id": eid,
                        "intent": row.get("action_type"),
                        "steps": [
                            {
                                "id": f"audit_{row.get('id')}",
                                "label": row.get("action_type"),
                                "status": row.get("status"),
                                "reasoning": row.get("reasoning_summary") or row.get("why_action_taken"),
                                "data_used": row.get("data_influenced_json") or row.get("payload_json") or {},
                            }
                        ],
                        "reasoning": row.get("reasoning_summary") or row.get("why_action_taken"),
                        "data_used": row.get("data_influenced_json") or row.get("payload_json") or {},
                    }
        raise HTTPException(status_code=404, detail="Decision trace not found")

    steps = []
    for idx, row in enumerate(rows, start=1):
        steps.append(
            {
                "id": f"s{idx}",
                "label": str(row.action_type or ""),
                "status": str(row.status or ""),
                "reasoning": row.reasoning_summary or row.why_action_taken or "",
                "data_used": row.data_influenced_json or row.payload_json or {},
                "result": row.result_json or {},
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return {
        "ok": True,
        "execution_id": eid,
        "intent": str(rows[0].action_type or ""),
        "steps": steps,
        "reasoning": rows[-1].reasoning_summary or rows[-1].why_action_taken or "",
        "data_used": rows[-1].data_influenced_json or rows[-1].payload_json or {},
    }
