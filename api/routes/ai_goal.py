"""
HTTP surface for THIRAMAI autonomous goal runs (orchestrator thread pool).

RBAC: submit/manager+, read/viewer+, cancel-pause/admin+, approve/manager+, internal/admin-only.
Multi-tenant: every job carries ``user_id`` + ``organization_id``; routes enforce isolation.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from starlette.requests import Request
from pydantic import BaseModel, Field

from api.dependencies import (
    CurrentUser,
    require_autonomy_admin_actions,
    require_autonomy_internal_ops,
    require_goal_read_access,
    require_internal_client_when_production,
    require_roles,
    try_resolve_current_user_from_access_token,
)

router = APIRouter(prefix="/ai", tags=["THIRAMAI Autonomy Goals"])
router_v1_ai = APIRouter(prefix="/v1/ai", tags=["THIRAMAI Autonomy Goals v1"])


def _ensure_job_access(user: CurrentUser, job_id: str) -> None:
    from thiramai.runtime import goal_jobs

    row = goal_jobs.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not goal_jobs.user_can_access_goal_job(user, row):
        raise HTTPException(status_code=403, detail="access denied")


class GoalSubmitBody(BaseModel):
    goal: str = Field(..., min_length=1, max_length=4000)
    max_seconds: int | None = Field(None, ge=30, le=7200)
    idempotency_key: str | None = Field(None, max_length=512)
    force_refresh: bool = Field(False, description="Bypass goal result cache for this submission")


@router.get("/version", summary="THIRAMAI build/version identifier")
def thiramai_build_version() -> dict[str, object]:
    from thiramai.config import (
        THIRAMAI_GOAL_CACHE_DATA_VERSION,
        THIRAMAI_SAFE_MODE,
        THIRAMAI_VERSION_ID,
    )
    from thiramai.runtime.goal_sqlite_migrations import GOAL_SQLITE_SCHEMA_VERSION

    return {
        "ok": True,
        "version_id": THIRAMAI_VERSION_ID,
        "goal_cache_data_version": THIRAMAI_GOAL_CACHE_DATA_VERSION,
        "goal_sqlite_schema_version": GOAL_SQLITE_SCHEMA_VERSION,
        "safe_mode": bool(THIRAMAI_SAFE_MODE),
    }


def _submit_autonomous_goal_impl(body: GoalSubmitBody, user: CurrentUser) -> dict[str, object]:
    from thiramai.runtime import billing_quota
    from thiramai.runtime import goal_jobs
    from thiramai.runtime.goal_jobs import IdempotencyConflictError

    try:
        submit_out = goal_jobs.submit_goal(
            body.goal.strip(),
            max_seconds=body.max_seconds,
            user_id=int(user.id),
            organization_id=int(user.organization_id),
            idempotency_key=body.idempotency_key,
            force_refresh=bool(body.force_refresh),
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        code = 400
        if "quota" in msg.lower() or "budget" in msg.lower():
            code = 429
        elif "overloaded" in msg.lower() or "maximum concurrent" in msg.lower():
            code = 429
        elif "shutting down" in msg.lower():
            code = 503
        raise HTTPException(status_code=code, detail=msg) from exc

    job_id = str(submit_out["job_id"])
    if not submit_out.get("idempotent_replay") and not submit_out.get("from_cache"):
        billing_quota.record_api_call(int(user.organization_id), int(user.id))

    out: dict[str, object] = {"ok": True, "job_id": job_id}
    if submit_out.get("idempotent_replay"):
        out["idempotent_replay"] = True
    if submit_out.get("from_cache"):
        out["from_cache"] = True
        row = goal_jobs.get_job(job_id)
        if row is not None:
            out["job"] = goal_jobs.public_job_view(row)
    return out


def _autonomous_goal_status_impl(job_id: str, user: CurrentUser) -> dict[str, object]:
    from thiramai.runtime import goal_jobs

    _ensure_job_access(user, job_id)
    row = goal_jobs.get_job(job_id)
    assert row is not None
    return goal_jobs.public_job_view(row)


@router.post("/goal")
def submit_autonomous_goal(
    body: GoalSubmitBody,
    user: CurrentUser = Depends(require_roles("owner", "manager", "admin")),
) -> dict[str, object]:
    try:
        return _submit_autonomous_goal_impl(body, user)
    except HTTPException:
        raise
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"THIRAMAI orchestrator unavailable: {exc}") from exc


@router_v1_ai.post("/goal")
def submit_autonomous_goal_v1(
    body: GoalSubmitBody,
    user: CurrentUser = Depends(require_roles("owner", "manager", "admin")),
) -> dict[str, object]:
    try:
        return _submit_autonomous_goal_impl(body, user)
    except HTTPException:
        raise
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"THIRAMAI orchestrator unavailable: {exc}") from exc


@router.get("/status")
def autonomous_goal_status(
    job_id: str = Query(..., min_length=8, max_length=64),
    user: CurrentUser = Depends(require_goal_read_access()),
) -> dict[str, object]:
    return _autonomous_goal_status_impl(job_id, user)


@router_v1_ai.get("/status")
def autonomous_goal_status_v1(
    job_id: str = Query(..., min_length=8, max_length=64),
    user: CurrentUser = Depends(require_goal_read_access()),
) -> dict[str, object]:
    return _autonomous_goal_status_impl(job_id, user)


@router.get("/history")
def autonomous_goal_history(
    limit: int = Query(25, ge=1, le=100),
    user: CurrentUser = Depends(require_goal_read_access()),
) -> dict[str, object]:
    from thiramai.runtime import goal_jobs

    jobs = [
        goal_jobs.public_job_view(j)
        for j in goal_jobs.list_recent_jobs_for_principal(user, limit)
    ]
    return {"ok": True, "jobs": jobs}


class JobIdBody(BaseModel):
    job_id: str = Field(..., min_length=8, max_length=64)


@router.post("/replay", summary="Re-run a job with the same goal payload (new job id)")
def replay_autonomous_goal(
    body: JobIdBody,
    user: CurrentUser = Depends(require_roles("owner", "manager", "admin")),
) -> dict[str, object]:
    from thiramai.runtime import billing_quota
    from thiramai.runtime import goal_jobs

    jid = body.job_id.strip()
    try:
        _ensure_job_access(user, jid)
        out = goal_jobs.replay_goal_job(
            jid,
            user_id=int(user.id),
            organization_id=int(user.organization_id),
        )
        billing_quota.record_api_call(int(user.organization_id), int(user.id))
    except ValueError as exc:
        msg = str(exc).lower()
        code = 400
        if "access denied" in msg or "not found" in msg:
            code = 404 if "not found" in msg else 403
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    new_id = str(out["job_id"])
    resp: dict[str, object] = {"ok": True, "job_id": new_id, "replayed_from": jid}
    return resp


@router.post("/cancel")
def cancel_goal_job(
    body: JobIdBody,
    user: CurrentUser = Depends(require_autonomy_admin_actions()),
) -> dict[str, object]:
    from thiramai.runtime import goal_jobs

    _ensure_job_access(user, body.job_id.strip())
    out = goal_jobs.cancel_job(body.job_id.strip())
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out)
    return out


@router.post("/pause")
def pause_goal_job(
    body: JobIdBody,
    user: CurrentUser = Depends(require_autonomy_admin_actions()),
) -> dict[str, object]:
    from thiramai.runtime import goal_jobs

    _ensure_job_access(user, body.job_id.strip())
    out = goal_jobs.pause_job(body.job_id.strip())
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out)
    return out


@router.post("/resume")
def resume_goal_job(
    body: JobIdBody,
    user: CurrentUser = Depends(require_autonomy_admin_actions()),
) -> dict[str, object]:
    from thiramai.runtime import goal_jobs

    _ensure_job_access(user, body.job_id.strip())
    out = goal_jobs.resume_job(body.job_id.strip())
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out)
    return out


@router.get("/logs")
def goal_job_logs(
    job_id: str = Query(..., min_length=8, max_length=64),
    tail: int = Query(100, ge=1, le=800),
    user: CurrentUser = Depends(require_goal_read_access()),
) -> dict[str, object]:
    from thiramai.runtime import goal_jobs

    _ensure_job_access(user, job_id)
    return {
        "ok": True,
        "job_id": job_id,
        "tail": tail,
        "logs": goal_jobs.get_job_logs(job_id, tail=tail),
    }


@router.websocket("/logs/ws/{job_id}")
async def goal_job_logs_ws(websocket: WebSocket, job_id: str) -> None:
    raw = (websocket.query_params.get("token") or "").strip()
    if not raw:
        auth = (websocket.headers.get("authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            raw = auth[7:].strip()
    user = try_resolve_current_user_from_access_token(raw if raw else None)
    if user is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        from thiramai.runtime import goal_jobs

        row = goal_jobs.get_job(job_id)
        if not row or not goal_jobs.user_can_access_goal_job(user, row):
            await websocket.send_json({"ok": False, "error": "job not found"})
            await websocket.close(code=1008)
            return
        while True:
            logs = goal_jobs.get_job_logs(job_id, tail=120)
            await websocket.send_json({"ok": True, "job_id": job_id, "logs": logs})
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return


@router.get("/workers")
def goal_workers_status(
    user: CurrentUser = Depends(require_goal_read_access()),
) -> dict[str, object]:
    from thiramai.runtime import goal_jobs

    return goal_jobs.workers_snapshot(organization_id=int(user.organization_id))


@router.get("/queue")
def goal_queue_inspect(
    user: CurrentUser = Depends(require_goal_read_access()),
) -> dict[str, object]:
    from thiramai.runtime import goal_jobs

    return goal_jobs.queue_snapshot(organization_id=int(user.organization_id))


class ApprovalActionBody(BaseModel):
    approval_id: str = Field(..., min_length=8, max_length=64)


class RejectApprovalBody(BaseModel):
    approval_id: str = Field(..., min_length=8, max_length=64)
    reason: str = Field("", max_length=500)


@router.get("/approvals")
def list_risk_approvals(
    user: CurrentUser = Depends(require_goal_read_access()),
) -> dict[str, object]:
    from thiramai.runtime import approval_store

    return {"ok": True, "pending": approval_store.list_pending()}


@router.post("/approve")
def approve_risk_task(
    body: ApprovalActionBody,
    user: CurrentUser = Depends(require_roles("owner", "manager", "admin")),
) -> dict[str, object]:
    from thiramai.runtime import approval_store

    out = approval_store.approve(body.approval_id.strip(), approved_by=user.email)
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=str(out.get("error", "not_found")))
    return out


@router.post("/reject")
def reject_risk_task(
    body: RejectApprovalBody,
    user: CurrentUser = Depends(require_roles("owner", "manager", "admin")),
) -> dict[str, object]:
    from thiramai.runtime import approval_store

    reason = (body.reason or "").strip() or f"rejected_by:{user.email}"
    out = approval_store.reject(body.approval_id.strip(), reason=reason)
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=str(out.get("error", "not_found")))
    return out


@router.get("/internal/state")
def autonomous_internal_state(
    request: Request,
    user: CurrentUser = Depends(require_autonomy_internal_ops()),
) -> dict[str, object]:
    require_internal_client_when_production(request)
    from dataclasses import asdict

    from core.stability.circuit_breaker import export_breaker_snapshots
    from core.stability.resource_monitor import snapshot

    from thiramai.runtime import ai_observability
    from thiramai.runtime import approval_store
    from thiramai.runtime import goal_jobs

    return {
        "ok": True,
        "resource": asdict(snapshot()),
        "goal_jobs_running": goal_jobs.count_running_jobs(),
        "counters": ai_observability.snapshot_counters(),
        "circuit_breakers": export_breaker_snapshots(),
        "pending_approvals": len(approval_store.list_pending()),
    }


@router.get("/internal/metrics")
def autonomous_internal_metrics(
    request: Request,
    user: CurrentUser = Depends(require_autonomy_internal_ops()),
) -> dict[str, object]:
    require_internal_client_when_production(request)
    """Compact operational metrics (subset of ``/internal/state`` for dashboards)."""
    from dataclasses import asdict

    from core.stability.circuit_breaker import export_breaker_snapshots
    from core.stability.resource_monitor import snapshot

    from thiramai.runtime import ai_observability
    from thiramai.runtime import goal_jobs

    ctr = ai_observability.snapshot_counters()
    gj = goal_jobs.aggregate_metrics()
    lat = ai_observability.advanced_latency_snapshot()
    return {
        "ok": True,
        "resource": asdict(snapshot()),
        "autonomy_counters": ctr,
        "performance": {
            "goal_jobs_avg_duration_ms": gj.get("avg_execution_ms"),
            "goal_jobs_completed_tracked": gj.get("jobs_completed"),
            "goal_jobs_running": gj.get("jobs_running"),
            "avg_llm_latency_ms": ctr.get("llm_avg_latency_ms"),
            "llm_success_rate": ctr.get("llm_success_rate"),
            "goal_success_rate": ctr.get("goal_jobs_success_rate"),
            "latency_percentiles": lat,
        },
        "circuit_breakers_open": sum(
            1 for b in export_breaker_snapshots() if str(b.get("state")) == "open"
        ),
        "goal_jobs_running": goal_jobs.count_running_jobs(),
    }


@router.get("/internal/last-errors")
def autonomous_internal_last_errors(
    request: Request,
    limit: int = Query(25, ge=1, le=50),
    user: CurrentUser = Depends(require_autonomy_internal_ops()),
) -> dict[str, object]:
    require_internal_client_when_production(request)
    from thiramai.runtime import ai_observability

    return {"ok": True, "errors": ai_observability.last_errors(limit)}
