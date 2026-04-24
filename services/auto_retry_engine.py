"""
Automatic retry for action execution runs after closure (bounded, no user input).

Called by execution closure authority to request retry through ``brain_execute``.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import ActionExecutionRun, ActionExecutionStep
from services.brain_execute import brain_execute
from services.domain_execution_intelligence import apply_domain_retry_strategy
from services.execution_memory_store import build_system_failure_playbook
from services.execution_learning_integration import apply_execution_retry_learning

_MAX_AUTO_RETRIES = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _update_parent_retry_state(
    *,
    run_id: int,
    status: str,
    retry_scheduled_at: str | None = None,
    retry_executed_at: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    fn = _session_factory_or_none()
    if fn is None:
        return
    with fn() as session:
        with session.begin():
            parent = (
                session.execute(select(ActionExecutionRun).where(ActionExecutionRun.id == int(run_id)).with_for_update())
                .scalars()
                .one_or_none()
            )
            if parent is None:
                return
            meta = dict(parent.meta_json or {})
            retry_job = meta.get("retry_job") if isinstance(meta.get("retry_job"), dict) else {}
            if retry_scheduled_at is not None:
                retry_job["retry_scheduled_at"] = retry_scheduled_at
            if retry_executed_at is not None:
                retry_job["retry_executed_at"] = retry_executed_at
            retry_job["retry_status"] = str(status or "unknown")
            if isinstance(details, dict) and details:
                retry_job["details"] = {**dict(retry_job.get("details") or {}), **details}
            meta["retry_job"] = retry_job
            rh = list(meta.get("retry_history") or [])
            rh.append(
                {
                    "retry_scheduled_at": retry_job.get("retry_scheduled_at"),
                    "retry_executed_at": retry_job.get("retry_executed_at"),
                    "retry_status": retry_job.get("retry_status"),
                    "details": dict(retry_job.get("details") or {}),
                }
            )
            meta["retry_history"] = rh[-50:]
            parent.meta_json = meta
            parent.updated_at = _now()


def _retry_steps_to_plan(retry_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for raw in retry_steps or []:
        if not isinstance(raw, dict):
            continue
        plan.append(
            {
                "step_order": int(raw.get("step_order") or 0),
                "phase": str(raw.get("phase") or "act"),
                "step_kind": str(raw.get("step_kind") or ""),
                "risk_level": str(raw.get("risk_level") or "medium"),
                "payload": dict(raw.get("payload") or {}),
            }
        )
    return [p for p in plan if p.get("step_kind")]


def _reserve_and_create_child_run_atomic(
    *,
    run_id: int,
    retry_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Atomic retry reservation + child creation.

    Guarantees within one DB transaction for a locked parent row:
    1) check retry_count
    2) increment retry_count
    3) create child run (+steps)
    4) link parent -> child
    """
    fn = _session_factory_or_none()
    if fn is None:
        return {"ok": False, "status": "database_unavailable"}
    with fn() as session:
        with session.begin():
            parent = (
                session.execute(
                    select(ActionExecutionRun)
                    .where(ActionExecutionRun.id == int(run_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if parent is None:
                return {"ok": False, "status": "run_not_found"}

            parent_meta = dict(parent.meta_json or {})
            gov = parent_meta.get("autonomy_governor_decision") if isinstance(parent_meta.get("autonomy_governor_decision"), dict) else {}
            retry_policy = gov.get("retry_policy") if isinstance(gov.get("retry_policy"), dict) else {}
            if bool(retry_policy.get("strategy_blocked")):
                return {"ok": False, "status": "strategy_blocked_by_failure_intelligence"}
            retry_job = parent_meta.get("retry_job") if isinstance(parent_meta.get("retry_job"), dict) else {}
            ar = dict(parent_meta.get("auto_retry") if isinstance(parent_meta.get("auto_retry"), dict) else {})
            hist = (
                parent_meta.get("execution_history_context")
                if isinstance(parent_meta.get("execution_history_context"), dict)
                else {}
            )
            domain_ctx = (
                parent_meta.get("execution_domain_context")
                if isinstance(parent_meta.get("execution_domain_context"), dict)
                else {}
            )
            retry_count = int(ar.get("count") or 0)
            retry_hint = str(hist.get("retry_strategy_hint") or "normal")
            dynamic_max_retries = _MAX_AUTO_RETRIES
            if retry_hint == "conservative_retry":
                dynamic_max_retries = max(1, _MAX_AUTO_RETRIES - 1)
            policy_max_retry = int(retry_policy.get("max_retry_depth") or _MAX_AUTO_RETRIES)
            dynamic_max_retries = min(dynamic_max_retries, max(0, policy_max_retry))
            if retry_count >= _MAX_AUTO_RETRIES:
                return {"ok": False, "status": "max_retries_exceeded"}
            if retry_count >= dynamic_max_retries:
                return {
                    "ok": False,
                    "status": "history_retry_limit_reached",
                    "retry_strategy_hint": retry_hint,
                }

            uid = int(parent.user_id)
            oid = int(parent.organization_id)
            attempt = retry_count + 1

            playbook = build_system_failure_playbook(
                user_id=uid,
                organization_id=oid,
                limit=260,
                min_cluster_count=2,
            )
            retry_steps_mut = _apply_failure_playbook_to_retry_steps(retry_steps, playbook=playbook)
            retry_steps_mut = apply_domain_retry_strategy(retry_steps_mut, domain_context=domain_ctx)
            plan_steps = _retry_steps_to_plan(retry_steps_mut)
            if not plan_steps:
                return {"ok": False, "status": "no_retry_steps"}

            cmd = str(parent.source_command or "").strip()[:8000]
            suffix = f" [auto-retry parent={int(run_id)} attempt={attempt}]"
            new_cmd = (cmd + suffix)[:8000]
            preflight_extras: dict[str, Any] = {
                "batch_medium_ok": True,
                "auto_retry": True,
                "auto_retry_parent_run_id": int(run_id),
                "auto_retry_attempt": int(attempt),
                "execution_history_context": {
                    **hist,
                    "parent_run_id": int(run_id),
                    "retry_strategy_hint": retry_hint,
                },
                "execution_domain_context": domain_ctx,
                "system_failure_playbook": playbook,
                "auto_retry_child": {"parent_run_id": int(run_id), "attempt": int(attempt)},
            }

            child = ActionExecutionRun(
                user_id=uid,
                organization_id=oid,
                source_command=new_cmd,
                status="planned",
                meta_json=preflight_extras,
                continuity_goal_id=None,
            )
            session.add(child)
            session.flush()

            for row in plan_steps:
                session.add(
                    ActionExecutionStep(
                        run_id=int(child.id),
                        step_order=int(row.get("step_order") or 0),
                        phase=str(row.get("phase") or "act"),
                        step_kind=str(row.get("step_kind") or ""),
                        risk_level=str(row.get("risk_level") or "medium"),
                        status="pending",
                        payload_json=dict(row.get("payload") or {}),
                        result_json={},
                    )
                )

            children = [int(x) for x in ar.get("children") or [] if int(x) > 0]
            children.append(int(child.id))
            ar["count"] = attempt
            ar["children"] = children
            ar["last_child_run_id"] = int(child.id)
            ar["last_retried_at"] = _now().isoformat()
            parent_meta["auto_retry"] = ar
            parent_meta["retry_job"] = {
                **retry_job,
                "retry_scheduled_at": str(retry_job.get("retry_scheduled_at") or _now().isoformat()),
                "retry_executed_at": _now().isoformat(),
                "retry_status": "running",
                "attempt": int(attempt),
                "parent_run_id": int(run_id),
                "child_run_id": int(child.id),
            }
            if isinstance(playbook, dict):
                parent_meta["system_failure_playbook"] = playbook
            parent.meta_json = parent_meta
            parent.updated_at = _now()

            return {
                "ok": True,
                "status": "reserved",
                "new_run_id": int(child.id),
                "attempt": int(attempt),
                "user_id": uid,
                "organization_id": oid,
                "retry_strategy_hint": retry_hint,
                "system_failure_playbook": playbook,
                "plan_step_count": len(plan_steps),
            }


def _execution_status(exec_res: dict[str, Any] | None) -> str:
    if not exec_res or not isinstance(exec_res, dict):
        return "unknown"
    if exec_res.get("ok") is True:
        return "success"
    if exec_res.get("partial"):
        return "partial"
    if exec_res.get("stopped"):
        return "stopped"
    return "failed"


def _apply_failure_playbook_to_retry_steps(
    retry_steps: list[dict[str, Any]],
    *,
    playbook: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    pb = playbook if isinstance(playbook, dict) else {}
    strategies = list(pb.get("strategies") or [])
    if not retry_steps or not strategies:
        return retry_steps
    out: list[dict[str, Any]] = []
    for raw in retry_steps:
        if not isinstance(raw, dict):
            continue
        step = dict(raw)
        sk = str(step.get("step_kind") or "")
        payload = dict(step.get("payload") or {})
        reason = str(step.get("reason") or "").lower()
        applied: list[dict[str, Any]] = []
        for item in strategies:
            if not isinstance(item, dict):
                continue
            cl = item.get("cluster") if isinstance(item.get("cluster"), dict) else {}
            st = item.get("strategy") if isinstance(item.get("strategy"), dict) else {}
            cl_step = str(cl.get("step_kind") or "")
            cl_err = str(cl.get("error_class") or "").lower()
            if cl_step and cl_step != sk:
                continue
            # match by step + failure reason/error class hint
            if cl_err and cl_err not in reason and cl_err != "unknown":
                continue
            muts = st.get("mutations") if isinstance(st.get("mutations"), dict) else {}
            if muts:
                payload = {**payload, **muts}
            applied.append(
                {
                    "cluster": {
                        "error_class": cl.get("error_class"),
                        "step_kind": cl.get("step_kind"),
                        "domain": cl.get("domain"),
                        "count": cl.get("count"),
                    },
                    "strategy_type": st.get("strategy_type"),
                    "reason": st.get("reason"),
                }
            )
        if applied:
            step["payload"] = payload
            step["failure_strategy_applied"] = applied
        out.append(step)
    return out


def _retry_window_exceeded(*, user_id: int, organization_id: int) -> dict[str, Any]:
    window_min = max(1, int((os.getenv("THIRAMAI_RETRY_WINDOW_MINUTES") or "30").strip() or 30))
    max_retries = max(1, int((os.getenv("THIRAMAI_MAX_RETRIES_PER_WINDOW") or "20").strip() or 20))
    fn = _session_factory_or_none()
    if fn is None:
        return {"ok": True}
    cutoff = _now().replace(microsecond=0) - timedelta(minutes=window_min)
    with fn() as session:
        rows = session.execute(
            select(ActionExecutionRun.id).where(
                ActionExecutionRun.user_id == int(user_id),
                ActionExecutionRun.organization_id == int(organization_id),
                ActionExecutionRun.created_at >= cutoff,
                ActionExecutionRun.source_command.ilike("%[auto-retry parent=%"),
            ).limit(max_retries + 1)
        ).all()
    n = len(rows)
    if n >= max_retries:
        return {"ok": False, "reason": "max_retries_per_window_reached", "value": n, "limit": max_retries, "window_minutes": window_min}
    return {"ok": True, "value": n, "limit": max_retries, "window_minutes": window_min}


def auto_retry_execution(
    run_id: int,
    *,
    retry_steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Execute retry for a parent run using closure-provided ``retry_steps``.

    Closure authority decides *if* retry is needed. This function only executes
    the retry flow and never calls closure itself.

    Returns:
        ``retried``, ``new_run_id``, ``status`` (plus ``execution`` for observability).
    """
    base = {
        "retried": False,
        "new_run_id": None,
        "status": "skipped",
        "execution": None,
    }
    provided_retry_steps = [x for x in (retry_steps or []) if isinstance(x, dict)]
    if not provided_retry_steps:
        base["status"] = "no_retry_steps_provided"
        _update_parent_retry_state(
            run_id=int(run_id),
            status="failed",
            retry_executed_at=_now().isoformat(),
            details={"reason": "no_retry_steps_provided"},
        )
        return base

    fn = _session_factory_or_none()
    if fn is None:
        base["status"] = "database_unavailable"
        return base
    with fn() as session:
        parent = session.execute(select(ActionExecutionRun).where(ActionExecutionRun.id == int(run_id))).scalar_one_or_none()
    if parent is None:
        base["status"] = "run_not_found"
        return base
    uid = int(parent.user_id)
    oid = int(parent.organization_id)
    retry_guard = _retry_window_exceeded(user_id=uid, organization_id=oid)
    if not bool(retry_guard.get("ok")):
        base["status"] = str(retry_guard.get("reason") or "retry_window_limited")
        _update_parent_retry_state(
            run_id=int(run_id),
            status="failed",
            retry_executed_at=_now().isoformat(),
            details={
                "reason": base["status"],
                "limit": retry_guard.get("limit"),
                "value": retry_guard.get("value"),
                "window_minutes": retry_guard.get("window_minutes"),
            },
        )
        return base
    cmd = str(parent.source_command or "").strip()
    if not cmd:
        base["status"] = "empty_parent_command"
        _update_parent_retry_state(
            run_id=int(run_id),
            status="failed",
            retry_executed_at=_now().isoformat(),
            details={"reason": "empty_parent_command"},
        )
        return base
    retry_suffix = f" [auto-retry parent={int(run_id)}]"
    cmd_retry = f"{cmd}{retry_suffix}"[:8000]
    exec_res = brain_execute(command=cmd_retry, user_id=uid, organization_id=oid)
    new_run_id = int(
        ((exec_res.get("result") if isinstance(exec_res, dict) else {}) or {}).get("run_id")
        or exec_res.get("run_id")
        or 0
    )

    try:
        base["retry_learning"] = apply_execution_retry_learning(
            user_id=uid,
            organization_id=oid,
            parent_run_id=int(run_id),
            child_run_id=int(new_run_id),
            attempt=1,
            plan_step_count=len(provided_retry_steps),
            exec_res=exec_res if isinstance(exec_res, dict) else {},
        )
    except Exception as exc:  # noqa: BLE001
        base["retry_learning"] = {"ok": False, "error": str(exc)[:500]}

    base["retried"] = True
    base["new_run_id"] = new_run_id
    base["retry_strategy_hint"] = "normal"
    base["status"] = _execution_status(exec_res if isinstance(exec_res, dict) else {})
    base["execution"] = exec_res if isinstance(exec_res, dict) else None
    _update_parent_retry_state(
        run_id=int(run_id),
        status="completed" if base["status"] in ("success", "partial") else "failed",
        retry_executed_at=_now().isoformat(),
        details={"execution_status": base["status"], "child_run_id": int(new_run_id)},
    )
    return base
