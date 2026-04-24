"""
Post-execution analysis for persisted action runs (no side-effect execution).

``handle_execution_closure`` loads ``ActionExecutionRun`` + steps, classifies outcome,
updates run status / meta, then records learning (``source_type="execution"``) plus
feedback calibration and ``update_strategy_profiles`` via ``execution_learning_integration``.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import get_session_factory
from core.db.models import ActionExecutionRun, ActionExecutionStep
from services.execution_learning_integration import apply_execution_closure_learning
from services.lifecycle_state import (
    LIFECYCLE_COMPLETED,
    LIFECYCLE_FAILED,
    LIFECYCLE_RETRYING,
    transition_lifecycle_state,
)

_ASSESSMENT_VALUES = frozenset({"match", "partial", "mismatch"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _retry_cooldown_seconds() -> int:
    raw = (os.getenv("THIRAMAI_RETRY_COOLDOWN_SECONDS") or "300").strip()
    try:
        return max(30, min(86400, int(raw)))
    except ValueError:
        return 300


def _append_closure_history(meta: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    hist = list(meta.get("closure_history") or [])
    hist.append(row)
    meta["closure_history"] = hist[-100:]
    return meta


def _schedule_retry_durable(*, run: ActionExecutionRun, meta: dict[str, Any], retry_steps: list[dict[str, Any]]) -> dict[str, Any]:
    now = _now()
    cooldown_sec = _retry_cooldown_seconds()
    pattern_key = "|".join(sorted({str(x.get("step_kind") or "") for x in retry_steps if isinstance(x, dict)}))
    suppression = meta.get("pattern_suppression") if isinstance(meta.get("pattern_suppression"), dict) else {}
    sup_until_raw = str(suppression.get(pattern_key) or "")
    sup_until: datetime | None = None
    if sup_until_raw:
        try:
            sup_until = datetime.fromisoformat(sup_until_raw.replace("Z", "+00:00"))
        except ValueError:
            sup_until = None
    if sup_until is not None and sup_until > now:
        meta["retry_job"] = {
            "run_id": int(run.id),
            "retry_scheduled_at": now.isoformat(),
            "retry_executed_at": now.isoformat(),
            "retry_status": "failed",
            "reason": "pattern_suppression_active",
        }
        return {"queued": False, "mode": "suppressed", "reason": "pattern_suppression_active", "suppressed_until": sup_until.isoformat()}
    retry_job = {
        "run_id": int(run.id),
        "retry_steps": list(retry_steps or []),
        "retry_scheduled_at": now.isoformat(),
        "retry_executed_at": None,
        "retry_status": "scheduled",
        "next_attempt_not_before": (now + timedelta(seconds=max(1, cooldown_sec))).isoformat(),
        "cooldown_until": (now + timedelta(seconds=max(1, cooldown_sec))).isoformat(),
    }
    meta["retry_job"] = retry_job
    return {"queued": True, "mode": "durable_db_retry_job", "run_id": int(run.id), "retry_status": "scheduled", "retry_scheduled_at": retry_job["retry_scheduled_at"]}


def _step_payload(step: ActionExecutionStep) -> dict[str, Any]:
    return dict(step.payload_json or {})


def _step_result_ok(step: ActionExecutionStep) -> bool | None:
    r = step.result_json if isinstance(step.result_json, dict) else {}
    if "ok" in r:
        return bool(r.get("ok"))
    return None


def _infer_outcome_assessment(run: ActionExecutionRun, steps: list[ActionExecutionStep]) -> str:
    """
    match: terminal success — run completed, no failed required steps.
    partial: mixed, pending, awaiting confirmation, or completed with some step failures.
    mismatch: cancelled, run-level failed, or all actionable steps failed / blocked.
    """
    rs = str(run.status or "").lower()
    if rs == "cancelled":
        return "mismatch"
    if rs == "failed":
        return "mismatch"

    ordered = sorted(steps, key=lambda s: int(s.step_order or 0))
    if not ordered:
        return "mismatch" if rs in ("failed", "cancelled") else "partial"

    pending = [s for s in ordered if str(s.status or "") in ("pending", "running")]
    awaiting = [s for s in ordered if str(s.status or "") == "awaiting_confirmation"]
    blocked = [s for s in ordered if str(s.status or "") == "blocked"]
    failed = [s for s in ordered if str(s.status or "") == "failed"]
    done_bad = [
        s
        for s in ordered
        if str(s.status or "") == "done" and _step_result_ok(s) is False
    ]
    skipped = [s for s in ordered if str(s.status or "") == "skipped"]

    if pending or awaiting:
        return "partial"
    if blocked and not any(str(s.status or "") == "done" for s in ordered):
        return "mismatch"
    if failed or done_bad:
        done_ok = [
            s
            for s in ordered
            if str(s.status or "") == "done" and (_step_result_ok(s) is not False)
        ]
        if done_ok:
            return "partial"
        return "mismatch"

    if rs == "completed":
        return "match"

    # planned / running at run level with all steps skipped
    if rs == "planned" and len(skipped) == len(ordered):
        return "mismatch"

    return "partial"


def _execution_tri_state(run: ActionExecutionRun, steps: list[ActionExecutionStep]) -> str:
    """Coarse bucket: done | partial | failed (for reporting)."""
    a = _effective_assessment(run, steps)
    if a == "match":
        return "done"
    if a == "partial":
        return "partial"
    return "failed"


def _effective_assessment(run: ActionExecutionRun, steps: list[ActionExecutionStep]) -> str:
    meta = run.meta_json if isinstance(run.meta_json, dict) else {}
    raw = str(meta.get("outcome_assessment") or "").strip().lower()
    if raw in _ASSESSMENT_VALUES:
        return raw
    return _infer_outcome_assessment(run, steps)


def _retry_steps_subset(steps: list[ActionExecutionStep], *, run_status: str) -> list[dict[str, Any]]:
    """Plan-shaped dicts for steps that should be retried or re-confirmed (analyze-only)."""
    out: list[dict[str, Any]] = []
    rs = str(run_status or "").lower()
    for s in sorted(steps, key=lambda x: int(x.step_order or 0)):
        st = str(s.status or "")
        reason = ""
        need = False
        if st in ("failed", "blocked"):
            need = True
            reason = str((s.result_json or {}).get("reason") or st)
        elif st == "awaiting_confirmation":
            need = True
            reason = "awaiting_confirmation"
        elif st == "done" and _step_result_ok(s) is False:
            need = True
            reason = str((s.result_json or {}).get("reason") or "step_ok_false")
        elif st == "pending" and rs in ("completed", "failed"):
            need = True
            reason = "unfinished_step"
        if not need:
            continue
        out.append(
            {
                "step_order": int(s.step_order or 0),
                "phase": str(s.phase or ""),
                "step_kind": str(s.step_kind or ""),
                "risk_level": str(s.risk_level or "medium"),
                "payload": _step_payload(s),
                "reason": reason[:500],
                "step_id": int(s.id),
            }
        )
    return out


def _confidence_from_run(run: ActionExecutionRun, steps: list[ActionExecutionStep]) -> dict[str, Any]:
    meta = run.meta_json if isinstance(run.meta_json, dict) else {}
    last = meta.get("last_confidence")
    if isinstance(last, dict) and last.get("score") is not None:
        return dict(last)
    n = len(steps)
    if n == 0:
        return {"score": 0.0, "success_rate": 0.0, "retries": 0, "time_s": 0.0, "failed_steps": 0}
    okn = sum(
        1
        for s in steps
        if str(s.status or "") == "done" and _step_result_ok(s) is not False
    )
    failed_n = sum(
        1
        for s in steps
        if str(s.status or "") == "failed" or (str(s.status or "") == "done" and _step_result_ok(s) is False)
    )
    success_rate = okn / n
    return {
        "score": round(max(0.0, min(1.0, success_rate)), 3),
        "success_rate": round(success_rate, 3),
        "retries": 0,
        "time_s": 0.0,
        "failed_steps": int(failed_n),
    }


def handle_execution_closure(run_id: int) -> dict[str, Any]:
    """
    Analyze a persisted action execution run and decide closure (no execution).

    Returns:
        * ``final_status``: ``completed`` | ``retry_needed`` | ``failed``
        * ``retry_steps``: subset of steps to retry (plan-shaped dicts), may be empty
        * ``confidence``: from run meta or derived from steps
    """
    factory = _session_factory_or_none()
    if factory is None:
        return {
            "final_status": "failed",
            "retry_steps": [],
            "confidence": {"score": 0.0, "success_rate": 0.0, "retries": 0, "time_s": 0.0, "failed_steps": 0},
            "ok": False,
            "error": "database_unavailable",
            "run_id": int(run_id),
        }

    with factory() as session:
        run = session.execute(
            select(ActionExecutionRun)
            .options(selectinload(ActionExecutionRun.steps))
            .where(ActionExecutionRun.id == int(run_id))
            .with_for_update()
        ).scalar_one_or_none()
        if run is None:
            return {
                "final_status": "failed",
                "retry_steps": [],
                "confidence": {"score": 0.0, "success_rate": 0.0, "retries": 0, "time_s": 0.0, "failed_steps": 0},
                "ok": False,
                "error": "run_not_found",
                "run_id": int(run_id),
            }
        if str(run.status or "").lower() == "running":
            return {
                "ok": True,
                "run_id": int(run_id),
                "skipped": True,
                "final_status": "running",
                "closure_status": "skip_closure_running",
                "retry_steps": [],
                "confidence": _confidence_from_run(run, list(run.steps or [])),
            }

        steps = list(run.steps or [])
        assessment = _effective_assessment(run, steps)
        tri = _execution_tri_state(run, steps)
        confidence = _confidence_from_run(run, steps)
        retry_steps = _retry_steps_subset(steps, run_status=str(run.status or ""))

        meta = dict(run.meta_json or {})
        timeline = meta.get("lifecycle_timeline") if isinstance(meta.get("lifecycle_timeline"), dict) else {}
        prev_closure = meta.get("execution_closure") if isinstance(meta.get("execution_closure"), dict) else {}
        if bool(prev_closure.get("locked")):
            return {
                "ok": True,
                "run_id": int(run_id),
                "skipped": True,
                "final_status": str(prev_closure.get("final_status") or "locked"),
                "closure_status": "locked_already_processed",
                "retry_steps": list(prev_closure.get("retry_steps") or []),
                "confidence": confidence,
            }
        prev_closure = {
            **prev_closure,
            "locked": True,
            "locked_at": _now().isoformat(),
        }
        meta["execution_closure"] = prev_closure
        run.meta_json = meta
        run.updated_at = _now()
        session.flush()

        learning_integration: dict[str, Any] | None = None
        failure_reason = ""

        if assessment == "match":
            if prev_closure.get("final_status") == "completed" and prev_closure.get("outcome_assessment") == "match":
                return {
                    "ok": True,
                    "run_id": int(run_id),
                    "final_status": "completed",
                    "retry_steps": [],
                    "confidence": confidence,
                    "outcome_assessment": assessment,
                    "execution_tri_state": tri,
                    "learning_record": None,
                    "learning_integration": None,
                    "idempotent": True,
                }
            if str(run.status or "").lower() not in ("cancelled",):
                run.status = "completed"
            meta["outcome_assessment"] = "match"
            meta["execution_closure"] = {
                **prev_closure,
                "final_status": "completed",
                "outcome_assessment": "match",
                "execution_tri_state": tri,
                "closed_at": _now().isoformat(),
            }
            timeline["closed_at"] = _now().isoformat()
            meta["lifecycle_timeline"] = timeline
            meta = _append_closure_history(
                meta,
                {
                    "at": _now().isoformat(),
                    "final_status": "completed",
                    "outcome_assessment": "match",
                    "retry_status": str(((meta.get("retry_job") if isinstance(meta.get("retry_job"), dict) else {}).get("retry_status") or "")),
                },
            )
            run.meta_json = meta
            run.updated_at = _now()
            allowed, updated_meta, _ = transition_lifecycle_state(
                meta_json=meta,
                next_state=LIFECYCLE_COMPLETED,
                transition_name="running_to_completed_by_closure",
            )
            if allowed:
                run.meta_json = updated_meta
                meta = updated_meta
            session.flush()
            session.commit()
            try:
                learning_integration = apply_execution_closure_learning(
                    user_id=int(run.user_id),
                    organization_id=int(run.organization_id),
                    run_id=int(run.id),
                    source_command=str(run.source_command or ""),
                    outcome_assessment=assessment,
                    final_status="completed",
                    success=True,
                    confidence=confidence,
                    steps_for_pnl=steps,
                )
            except Exception as exc:  # noqa: BLE001
                learning_integration = {"ok": False, "error": str(exc)[:500]}
            return {
                "ok": True,
                "run_id": int(run_id),
                "final_status": "completed",
                "retry_steps": [],
                "confidence": confidence,
                "outcome_assessment": assessment,
                "execution_tri_state": tri,
                "learning_record": learning_integration.get("record_outcome")
                if isinstance(learning_integration, dict)
                else None,
                "learning_integration": learning_integration,
                "closure_status": "closed",
                "retry_count": int(((meta.get("auto_retry") if isinstance(meta.get("auto_retry"), dict) else {}).get("count") or 0)),
                "last_transition": str((((meta.get("lifecycle") if isinstance(meta.get("lifecycle"), dict) else {}).get("last_transition")) or "")),
            }

        if assessment == "partial":
            if not retry_steps:
                # Dead-run recovery guarantee: no silent partial-without-retry path.
                if str(run.status or "").lower() != "cancelled":
                    run.status = "failed"
                meta["outcome_assessment"] = "mismatch"
                meta["execution_failure"] = {
                    **(meta.get("execution_failure") if isinstance(meta.get("execution_failure"), dict) else {}),
                    "reason": "partial_without_retry_steps",
                }
                meta["execution_closure"] = {
                    **prev_closure,
                    "final_status": "failed",
                    "outcome_assessment": "mismatch",
                    "execution_tri_state": tri,
                    "failure_reason": "partial_without_retry_steps",
                    "closed_at": _now().isoformat(),
                }
                allowed, updated_meta, _ = transition_lifecycle_state(
                    meta_json=meta,
                    next_state=LIFECYCLE_FAILED,
                    transition_name="running_to_failed_partial_without_retry_steps",
                )
                run.meta_json = updated_meta if allowed else meta
                run.updated_at = _now()
                session.commit()
                return {
                    "ok": True,
                    "run_id": int(run_id),
                    "final_status": "failed",
                    "retry_steps": [],
                    "confidence": confidence,
                    "outcome_assessment": "mismatch",
                    "execution_tri_state": tri,
                    "failure_reason": "partial_without_retry_steps",
                    "closure_status": "closed_dead_state_recovered",
                }
            meta["outcome_assessment"] = "partial"
            meta["execution_closure"] = {
                **prev_closure,
                "final_status": "retry_needed",
                "outcome_assessment": "partial",
                "execution_tri_state": tri,
                "retry_steps": retry_steps,
                "decided_at": _now().isoformat(),
            }
            meta = _append_closure_history(
                meta,
                {
                    "at": _now().isoformat(),
                    "final_status": "retry_needed",
                    "outcome_assessment": "partial",
                    "retry_status": "scheduled",
                },
            )
            retry_execution: dict[str, Any] | None = _schedule_retry_durable(
                run=run,
                meta=meta,
                retry_steps=retry_steps,
            )
            if not retry_execution.get("queued"):
                meta["execution_closure"] = {
                    **dict(meta.get("execution_closure") or {}),
                    "final_status": "failed",
                    "failure_reason": str(retry_execution.get("reason") or "retry_suppressed"),
                    "closed_at": _now().isoformat(),
                }
                timeline["closed_at"] = _now().isoformat()
                meta["lifecycle_timeline"] = timeline
                meta = _append_closure_history(
                    meta,
                    {
                        "at": _now().isoformat(),
                        "final_status": "failed",
                        "outcome_assessment": "mismatch",
                        "retry_status": "failed",
                        "reason": str(retry_execution.get("reason") or "retry_suppressed"),
                    },
                )
                run.status = "failed"
            next_state = LIFECYCLE_RETRYING if retry_execution.get("queued") else LIFECYCLE_FAILED
            allowed, updated_meta, _ = transition_lifecycle_state(
                meta_json=meta,
                next_state=next_state,
                transition_name=(
                    "running_to_retrying_by_closure"
                    if next_state == LIFECYCLE_RETRYING
                    else "running_to_failed_retry_suppressed_by_closure"
                ),
            )
            if allowed:
                meta = updated_meta
            run.meta_json = meta
            run.updated_at = _now()
            session.commit()
            try:
                learning_integration = apply_execution_closure_learning(
                    user_id=int(run.user_id),
                    organization_id=int(run.organization_id),
                    run_id=int(run.id),
                    source_command=str(run.source_command or ""),
                    outcome_assessment=assessment,
                    final_status="retry_needed" if retry_execution.get("queued") else "failed",
                    success=False if retry_execution.get("queued") else False,
                    confidence=confidence,
                    steps_for_pnl=steps,
                )
            except Exception as exc:  # noqa: BLE001
                learning_integration = {"ok": False, "error": str(exc)[:500]}
            return {
                "ok": True,
                "run_id": int(run_id),
                "final_status": "retry_needed" if retry_execution.get("queued") else "failed",
                "retry_steps": retry_steps,
                "confidence": confidence,
                "outcome_assessment": assessment,
                "execution_tri_state": tri,
                "learning_record": learning_integration.get("record_outcome")
                if isinstance(learning_integration, dict)
                else None,
                "learning_integration": learning_integration,
                "retry_execution": retry_execution,
                "closure_status": "closed_retry_queued" if retry_execution.get("queued") else "closed_retry_suppressed",
                "retry_count": int(((meta.get("auto_retry") if isinstance(meta.get("auto_retry"), dict) else {}).get("count") or 0)),
                "last_transition": str((((meta.get("lifecycle") if isinstance(meta.get("lifecycle"), dict) else {}).get("last_transition")) or "")),
            }

        # mismatch
        failure_reason = str((meta.get("execution_failure") or {}).get("reason") or "").strip()
        if not failure_reason:
            if str(run.status or "").lower() == "cancelled":
                failure_reason = "run_cancelled"
            elif str(run.status or "").lower() == "failed":
                failure_reason = "run_marked_failed"
            else:
                failure_reason = "outcome_mismatch"

        if str(run.status or "").lower() != "cancelled":
            run.status = "failed"
        meta["outcome_assessment"] = "mismatch"
        meta["execution_failure"] = {**(meta.get("execution_failure") if isinstance(meta.get("execution_failure"), dict) else {}), "reason": failure_reason[:800]}
        meta["execution_closure"] = {
            **prev_closure,
            "final_status": "failed",
            "outcome_assessment": "mismatch",
            "execution_tri_state": tri,
            "failure_reason": failure_reason[:800],
            "closed_at": _now().isoformat(),
        }
        if retry_steps:
            pattern_key = "|".join(sorted({str(x.get("step_kind") or "") for x in retry_steps if isinstance(x, dict)}))
            if pattern_key:
                sup = meta.get("pattern_suppression") if isinstance(meta.get("pattern_suppression"), dict) else {}
                sup[pattern_key] = (_now() + timedelta(minutes=30)).isoformat()
                meta["pattern_suppression"] = sup
        timeline["closed_at"] = _now().isoformat()
        meta["lifecycle_timeline"] = timeline
        meta = _append_closure_history(
            meta,
            {
                "at": _now().isoformat(),
                "final_status": "failed",
                "outcome_assessment": "mismatch",
                "retry_status": str(((meta.get("retry_job") if isinstance(meta.get("retry_job"), dict) else {}).get("retry_status") or "not_scheduled")),
                "reason": failure_reason[:800],
            },
        )
        allowed, updated_meta, _ = transition_lifecycle_state(
            meta_json=meta,
            next_state=LIFECYCLE_FAILED,
            transition_name="running_to_failed_by_closure",
        )
        if allowed:
            meta = updated_meta
        run.meta_json = meta
        run.updated_at = _now()
        session.commit()
        try:
            learning_integration = apply_execution_closure_learning(
                user_id=int(run.user_id),
                organization_id=int(run.organization_id),
                run_id=int(run.id),
                source_command=str(run.source_command or ""),
                outcome_assessment=assessment,
                final_status="failed",
                success=False,
                confidence=confidence,
                steps_for_pnl=steps,
            )
        except Exception as exc:  # noqa: BLE001
            learning_integration = {"ok": False, "error": str(exc)[:500]}
        return {
            "ok": True,
            "run_id": int(run_id),
            "final_status": "failed",
            "retry_steps": retry_steps,
            "confidence": confidence,
            "outcome_assessment": assessment,
            "execution_tri_state": tri,
            "failure_reason": failure_reason[:800],
            "learning_record": learning_integration.get("record_outcome")
            if isinstance(learning_integration, dict)
            else None,
            "learning_integration": learning_integration,
            "closure_status": "closed",
            "retry_count": int(((meta.get("auto_retry") if isinstance(meta.get("auto_retry"), dict) else {}).get("count") or 0)),
            "last_transition": str((((meta.get("lifecycle") if isinstance(meta.get("lifecycle"), dict) else {}).get("last_transition")) or "")),
        }
