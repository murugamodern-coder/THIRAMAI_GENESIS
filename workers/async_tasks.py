"""RQ task handlers for production async execution."""

from __future__ import annotations

from typing import Any

from services.automation_rule_engine import evaluate_rules
from services.execute_mission_store import MissionExecutionContext, run_mission_sequentially
from services.learning_engine import update_strategy_profiles
from services.opportunity_engine import scan_all_opportunities
from services.research_projects_engine import run_research_project
from services.brain_execute import brain_execute
from services.autonomous_continuity_engine import continuity_worker


def mission_execute(payload: dict[str, Any]) -> dict[str, Any]:
    mission_id = int(payload.get("mission_id") or 0)
    if mission_id <= 0:
        return {"ok": False, "error": "mission_id required"}
    ctx = MissionExecutionContext(
        user_id=int(payload.get("user_id") or 0),
        organization_id=int(payload.get("organization_id") or 0),
        role_name=str(payload.get("role_name") or "owner"),
    )
    return run_mission_sequentially(mission_id=mission_id, ctx=ctx)


def automation_evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    return evaluate_rules(payload or {})


def opportunity_scan(payload: dict[str, Any]) -> dict[str, Any]:
    uid = int(payload.get("user_id") or 0)
    oid = int(payload.get("organization_id") or 0)
    if uid <= 0 or oid <= 0:
        return {"ok": False, "error": "user_id and organization_id required"}
    return scan_all_opportunities(user_id=uid, organization_id=oid)


def learning_optimize(payload: dict[str, Any]) -> dict[str, Any]:
    uid = int(payload.get("user_id") or 0)
    if uid <= 0:
        return {"ok": False, "error": "user_id required"}
    return update_strategy_profiles(uid)


def research_project_run(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = int(payload.get("project_id") or 0)
    cycles = int(payload.get("cycles") or 3)
    if project_id <= 0:
        return {"ok": False, "error": "project_id required"}
    return run_research_project(project_id=project_id, cycles=cycles)


def action_plan_execute(payload: dict[str, Any]) -> dict[str, Any]:
    cmd = str((payload or {}).get("command") or "").strip()
    uid = int((payload or {}).get("user_id") or 0)
    oid = int((payload or {}).get("organization_id") or 0)
    if not cmd or uid <= 0 or oid <= 0:
        return {"ok": False, "error": "command, user_id, organization_id required"}
    return brain_execute(cmd, uid, oid)


def brain_execute_async(payload: dict[str, Any]) -> dict[str, Any]:
    cmd = str((payload or {}).get("command") or "").strip()
    uid = int((payload or {}).get("user_id") or 0)
    oid = int((payload or {}).get("organization_id") or 0)
    if not cmd or uid <= 0 or oid <= 0:
        return {"ok": False, "error": "command, user_id, organization_id required"}
    return brain_execute(cmd, uid, oid)


def continuity_tick(payload: dict[str, Any]) -> dict[str, Any]:
    return continuity_worker(payload or {})
