"""Action orchestrator: plan → confirm gates → execute with verification, retries, and memory."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import get_session_factory
from core.db.models import ActionExecutionRun, ActionExecutionStep
from core.execution_contract_guard import assert_execution_context
from services.action_plugins import run_plugin
from services.browser_automation_controller import BrowserAutomationController
from services.execution_memory_store import recent_hints
from services.execution_step_runner import run_step_with_perfection
from services.lifecycle_state import lifecycle_from_action_run
from services.lifecycle_state import (
    LIFECYCLE_CANCELLED,
    LIFECYCLE_COMPLETED,
    LIFECYCLE_FAILED,
    LIFECYCLE_RUNNING,
    transition_lifecycle_state,
)
from services.autonomy_safety_layer import (
    INTERNAL_SAFETY_ALWAYS_AUTO,
    apply_trust_damping,
    approval_tier_from_score,
    check_risk_budget,
    classify_action_step,
    get_system_trust_score,
    global_autonomy_halted,
    is_first_exposure,
    mark_step_kind_exposed,
    pre_execution_simulation_gate,
    sandbox_first_steps_enabled,
)
from services.governance_engine import log_execution, validate_action
from services.governance_engine import is_kill_switch_active
from services.task_decomposition import build_plan_steps_from_command, scan_context_hints


@dataclass(frozen=True)
class ActionExecutionContext:
    user_id: int
    organization_id: int
    role_name: str = ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _iso_now() -> str:
    return _now().isoformat()


def _ensure_run_observability_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    m = dict(meta or {})
    if not str(m.get("execution_trace_id") or "").strip():
        m["execution_trace_id"] = f"axr_{uuid.uuid4().hex}"
    timeline = m.get("lifecycle_timeline") if isinstance(m.get("lifecycle_timeline"), dict) else {}
    timeline.setdefault("created_at", _iso_now())
    timeline.setdefault("started_at", None)
    timeline.setdefault("last_step_at", None)
    timeline.setdefault("closed_at", None)
    m["lifecycle_timeline"] = timeline
    if not isinstance(m.get("retry_history"), list):
        m["retry_history"] = []
    if not isinstance(m.get("closure_history"), list):
        m["closure_history"] = []
    return m


def _compute_confidence(
    steps_out: list[dict[str, Any]],
    *,
    total_time_s: float,
    total_retries: int,
) -> dict[str, Any]:
    n = len(steps_out)
    if n == 0:
        return {
            "score": 0.0,
            "success_rate": 0.0,
            "retries": int(total_retries),
            "time_s": round(float(total_time_s), 2),
            "failed_steps": 0,
        }
    okn = sum(1 for s in steps_out if s.get("ok") is True)
    success_rate = okn / n
    rpen = min(0.4, 0.06 * max(0, int(total_retries)))
    tpen = min(0.12, max(0.0, (float(total_time_s) - 5.0) * 0.01))
    partial = okn < n
    score = max(0.0, min(1.0, success_rate * (1.0 - rpen) * (1.0 - tpen) * (0.88 if partial else 1.0)))
    return {
        "score": round(score, 3),
        "success_rate": round(success_rate, 3),
        "retries": int(total_retries),
        "time_s": round(float(total_time_s), 2),
        "failed_steps": int(n - okn),
        "partial_completion": bool(partial),
    }


def _dispatch_step(
    step_kind: str,
    payload: dict[str, Any],
    ctx: ActionExecutionContext,
) -> dict[str, Any]:
    sk = str(step_kind or "")
    if sk == "internal_context_scan":
        cmd = str(payload.get("command") or "")
        hints = scan_context_hints(cmd)
        return {"ok": True, **hints}
    if sk == "internal_command_analysis":
        return {"ok": True, "analysis": payload.get("signals") or {}}
    if sk == "internal_workflow_dependency_map":
        return {
            "ok": True,
            "workflow_type": payload.get("workflow_type") or "single_path",
            "sub_goals": payload.get("sub_goals") or [],
            "dependencies": payload.get("dependencies") or [],
        }
    if sk == "internal_execution_branch":
        return {"ok": True, "branch": payload.get("planned_plugins") or []}
    if sk == "internal_summarize":
        return {
            "ok": True,
            "summary": str(payload.get("message") or "complete"),
            "command": str(payload.get("command") or ""),
        }

    if sk.startswith("browser_"):
        assert_execution_context(required_run=True)
        with BrowserAutomationController() as b:
            if not b.available():
                return {"ok": False, "error": "playwright not installed (pip install playwright && playwright install chromium)"}
            if sk == "browser_open":
                url = str(payload.get("url") or "").strip()
                if not url:
                    return {"ok": False, "error": "url required"}
                return b.open_url(url)
            if sk == "browser_search":
                return b.search(str(payload.get("query") or ""), base_url=(payload.get("base_url") or None))
            if sk == "browser_click":
                return b.click(str(payload.get("selector") or ""))
            if sk == "browser_fill":
                fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
                return b.fill_form({str(k): str(v) for k, v in fields.items()})
        return {"ok": False, "error": "unknown browser step"}

    if sk.startswith("plugin_") or sk in {"plugin_email", "plugin_file", "plugin_api", "plugin_notify"}:
        assert_execution_context(required_run=True)
        name = sk.replace("plugin_", "") if sk.startswith("plugin_") else sk
        return run_plugin(name, payload, organization_id=int(ctx.organization_id))

    return {"ok": False, "error": f"unsupported step_kind: {sk}"}


def _attempt_alternative_path(
    *,
    step_order: int,
    phase: str,
    risk: str,
    payload: dict[str, Any],
    ctx: ActionExecutionContext,
) -> dict[str, Any] | None:
    alts = list(payload.get("alternative_paths") or []) if isinstance(payload, dict) else []
    if not alts:
        return None
    alt0 = alts[0] if isinstance(alts[0], dict) else {}
    alt_kind = str(alt0.get("step_kind") or "").strip()
    alt_payload = dict(alt0.get("payload") or {})
    if not alt_kind:
        return None
    out = run_step_with_perfection(
        int(step_order),
        str(phase or "act"),
        alt_kind,
        str(risk or "medium"),
        alt_payload,
        ctx,
        _dispatch_step,
    )
    return {
        "alternative_used": True,
        "alternative_step_kind": alt_kind,
        "alternative_result": out,
    }


def execute_action_plan(
    plan_steps: list[dict[str, Any]],
    *,
    ctx: ActionExecutionContext,
    run_id: int | None = None,
    max_retries: int = 2,
    brain_safety_preflight: bool = False,
    preflight_by_order: dict[str, Any] | None = None,
) -> dict[str, Any]:  # noqa: ARG001 — max_retries retained for API compatibility; perfection layer uses fixed rounds
    """
    Execute an in-memory list of plan steps (used by tests and as core loop for DB-backed runs).

    Each step: ``{ step_order, phase, step_kind, risk_level, payload }``.
    When ``run_id`` is set, persists per-step status/results on ``ActionExecutionStep`` rows.
    """
    factory = _session_factory_or_none()
    session_cm = factory() if factory and run_id else None
    steps_out: list[dict[str, Any]] = []
    stopped_early: dict[str, Any] | None = None

    try:
        if global_autonomy_halted():
            return {"ok": False, "error": "global_autonomy_halt", "steps": [], "run_id": run_id}
        if is_kill_switch_active(int(ctx.user_id)):
            return {"ok": False, "error": "kill_switch_enabled", "steps": [], "run_id": run_id}
        session = session_cm.__enter__() if session_cm else None
        db_steps: dict[int, ActionExecutionStep] = {}
        run_row: ActionExecutionRun | None = None
        if session is not None and run_id:
            run_row = session.execute(
                select(ActionExecutionRun).where(
                    ActionExecutionRun.id == int(run_id),
                    ActionExecutionRun.user_id == int(ctx.user_id),
                )
            ).scalar_one_or_none()
            if run_row is None:
                return {"ok": False, "error": "run not found"}
            if str(run_row.status or "") == "cancelled":
                return {"ok": False, "error": "run_cancelled", "steps": steps_out, "run_id": run_id}
            q = (
                select(ActionExecutionStep)
                .where(ActionExecutionStep.run_id == int(run_id))
                .order_by(ActionExecutionStep.step_order.asc(), ActionExecutionStep.id.asc())
            )
            for s in session.execute(q).scalars().all():
                db_steps[int(s.step_order)] = s

        source_cmd = str(run_row.source_command or "") if run_row else ""
        ordered = sorted(plan_steps, key=lambda x: int(x.get("step_order") or 0))
        t_plan0 = time.monotonic()
        total_retries_all = 0
        for spec in ordered:
            if is_kill_switch_active(int(ctx.user_id)):
                stopped_early = {"reason": "kill_switch_enabled"}
                break
            order = int(spec.get("step_order") or 0)
            phase = str(spec.get("phase") or "")
            step_kind = str(spec.get("step_kind") or "")
            row = db_steps.get(order) if db_steps else None

            # Safe interruption: always re-check persisted run status before each step.
            # This prevents further side-effects after an external cancellation request.
            if session is not None and run_id:
                latest_run = session.execute(
                    select(ActionExecutionRun).where(
                        ActionExecutionRun.id == int(run_id),
                        ActionExecutionRun.user_id == int(ctx.user_id),
                    )
                ).scalar_one_or_none()
                if latest_run is None:
                    stopped_early = {"reason": "run_not_found_during_execution", "step_order": order}
                    break
                if str(latest_run.status or "") == "cancelled":
                    stopped_early = {"reason": "run_cancelled", "step_order": order}
                    break

            risk = str((row.risk_level if row is not None else spec.get("risk_level")) or "medium").lower()
            payload: dict[str, Any]
            if row is not None:
                payload = dict(row.payload_json or {})
            else:
                payload = spec.get("payload") if isinstance(spec.get("payload"), dict) else {}

            hints = recent_hints(user_id=int(ctx.user_id), step_kind=step_kind, limit=3)
            if hints and not all(h.get("success") for h in hints[:1]):
                payload = {**payload, "memory_warning": "Recent failures recorded for similar steps."}

            if row is not None and str(row.status or "") == "done":
                steps_out.append(
                    {
                        "step_order": order,
                        "phase": phase,
                        "step_kind": step_kind,
                        "risk_level": risk,
                        "result": dict(row.result_json or {}),
                        "skipped": True,
                        "ok": True,
                        "outcome": "success",
                    }
                )
                continue

            pfp: dict[str, Any] | None = None
            if (
                brain_safety_preflight
                and preflight_by_order
                and isinstance(preflight_by_order, dict)
                and run_id
            ):
                raw = preflight_by_order.get(str(order))
                if isinstance(raw, dict) and "risk_score" in raw:
                    pfp = raw

            if pfp is not None:
                t_score = int(pfp.get("risk_score") or 0)
                eff_tier = str(pfp.get("tier") or "auto")
                pro = {
                    "category": str(pfp.get("category") or ""),
                    "risk_score": t_score,
                    "approval_tier": eff_tier,
                }
            else:
                pro = classify_action_step(
                    step_kind,
                    str((row.risk_level if row is not None else spec.get("risk_level")) or "medium"),
                    source_command=source_cmd,
                )
                t_score = int(
                    apply_trust_damping(int(pro.get("risk_score") or 0), get_system_trust_score(int(ctx.user_id)))
                )
                if step_kind in INTERNAL_SAFETY_ALWAYS_AUTO:
                    eff_tier = "auto"
                else:
                    eff_tier = str(approval_tier_from_score(t_score))

            if row is not None:
                meta = run_row.meta_json if run_row and isinstance(run_row.meta_json, dict) else {}
                if eff_tier == "explicit" and row.explicit_confirmed_at is None:
                    row.status = "awaiting_confirmation"
                    session.flush()
                    stopped_early = {
                        "reason": "high_risk_requires_explicit_ok",
                        "step_order": order,
                        "step_kind": step_kind,
                        "safety_tier": eff_tier,
                        "safety_risk_score": t_score,
                    }
                    break
                if eff_tier == "batch" and not bool(meta.get("batch_medium_ok")):
                    row.status = "awaiting_confirmation"
                    session.flush()
                    stopped_early = {
                        "reason": "medium_risk_batch_confirm_required",
                        "step_order": order,
                        "step_kind": step_kind,
                        "safety_tier": eff_tier,
                        "safety_risk_score": t_score,
                    }
                    break
                if pfp is None:
                    risk_for_budget = 0 if step_kind in INTERNAL_SAFETY_ALWAYS_AUTO else t_score
                    rbud = check_risk_budget(int(ctx.user_id), risk_for_budget)
                    if not rbud.get("allowed"):
                        row.status = "blocked"
                        br = {
                            "ok": False,
                            "blocked": True,
                            "reason": rbud.get("reason") or "risk_budget",
                            "safety_risk_score": t_score,
                        }
                        row.result_json = br
                        session.flush()
                        steps_out.append(
                            {
                                "step_order": order,
                                "phase": phase,
                                "step_kind": step_kind,
                                "risk_level": risk,
                                "result": br,
                                "ok": False,
                            }
                        )
                        stopped_early = {
                            "reason": "risk_budget_exceeded",
                            "step_order": order,
                            "step_kind": step_kind,
                            "detail": rbud.get("reason"),
                        }
                        break

            if pfp is None:
                gov = validate_action(
                    "action_layer_step",
                    {
                        "user_id": int(ctx.user_id),
                        "domain": "automation",
                        "payload": {
                            "run_id": run_id,
                            "step_kind": step_kind,
                            "risk_level": risk,
                            "safety_risk_score": t_score,
                        },
                    },
                )
                if not gov.get("allowed") and str(gov.get("reason") or "") == "Database unavailable":
                    if risk == "low" and (
                        step_kind.startswith("internal_")
                        or step_kind in {"plugin_notify", "plugin_file", "internal_summarize"}
                    ):
                        gov = {"ok": True, "allowed": True}
                if not gov.get("allowed"):
                    res = {"ok": False, "blocked": True, "reason": gov.get("reason") or "governance_blocked"}
                    steps_out.append({"step_order": order, "phase": phase, "step_kind": step_kind, "result": res})
                    if row is not None:
                        row.status = "blocked"
                        row.result_json = res
                        session.flush()
                    log_execution(
                        user_id=int(ctx.user_id),
                        action_type="action_layer_step",
                        source="action_engine",
                        payload_json={"run_id": run_id, "step_order": order, "step_kind": step_kind},
                        result_json=res,
                        status="blocked",
                        execution_id=f"action_run_{run_id}" if run_id else None,
                        reasoning_summary="Action step blocked by governance.",
                        why_action_taken="Safety validation rejected this step.",
                        data_influenced_json={"run_id": run_id, "step_order": order},
                    )
                    stopped_early = {"reason": "governance_blocked", "step_order": order}
                    break

            if row is not None:
                row.status = "running"
                session.flush()

            do_sandbox = (
                sandbox_first_steps_enabled()
                and is_first_exposure(int(ctx.user_id), step_kind)
                and not str(step_kind).startswith("internal_")
            )
            if do_sandbox:
                one = {
                    "step_order": order,
                    "phase": phase,
                    "step_kind": step_kind,
                    "risk_level": risk,
                    "ok": True,
                    "outcome": "success",
                    "retries": 0,
                    "result": {
                        "ok": True,
                        "dry_run": True,
                        "first_exposure": True,
                        "safety_risk_score": t_score,
                        "message": "First-time step kind: sandbox (no side effects). Re-run to execute for real.",
                    },
                }
                mark_step_kind_exposed(int(ctx.user_id), step_kind)
            else:
                one = run_step_with_perfection(
                    order, phase, step_kind, risk, payload, ctx, _dispatch_step
                )
                if not bool(one.get("ok")):
                    alt = _attempt_alternative_path(
                        step_order=order,
                        phase=phase,
                        risk=risk,
                        payload=payload,
                        ctx=ctx,
                    )
                    if isinstance(alt, dict):
                        one = {
                            **one,
                            "adaptive_refinement": {
                                "mid_execution_refinement": True,
                                **alt,
                            },
                            "ok": bool(((alt.get("alternative_result") or {}) if isinstance(alt.get("alternative_result"), dict) else {}).get("ok")),
                            "result": (
                                ((alt.get("alternative_result") or {}) if isinstance(alt.get("alternative_result"), dict) else {}).get("result")
                                if isinstance((alt.get("alternative_result") or {}), dict)
                                else one.get("result")
                            ),
                        }
            total_retries_all += int(one.get("retries") or 0)
            steps_out.append(one)

            if row is not None:
                res_body = one.get("result")
                if not isinstance(res_body, dict):
                    res_body = {}
                row.retry_count = int(one.get("retries") or 0)
                row.status = "done" if one.get("ok") else "failed"
                row.result_json = {
                    **res_body,
                    "heal_trace": one.get("heal_trace"),
                    "outcome": one.get("outcome"),
                    "verify_detail": one.get("verify_detail"),
                }
                if run_row is not None:
                    rm = _ensure_run_observability_meta(
                        run_row.meta_json if isinstance(run_row.meta_json, dict) else {}
                    )
                    tl = dict(rm.get("lifecycle_timeline") or {})
                    tl["last_step_at"] = _iso_now()
                    rm["lifecycle_timeline"] = tl
                    run_row.meta_json = rm
                session.flush()

            log_execution(
                user_id=int(ctx.user_id),
                action_type="action_layer_step",
                source="action_engine",
                payload_json={
                    "run_id": run_id,
                    "step_order": order,
                    "step_kind": step_kind,
                    "risk_level": risk,
                    "safety_risk_score": t_score,
                    "safety_category": str((pro or {}).get("category") or ""),
                },
                result_json=one.get("result") if isinstance(one.get("result"), dict) else {},
                status="success" if one.get("ok") else "failed",
                execution_id=f"action_run_{run_id}" if run_id else None,
                reasoning_summary="Action step with self-heal + verification (perfection layer).",
                why_action_taken=f"step_kind={step_kind} phase={phase} outcome={one.get('outcome')}.",
                data_influenced_json={"run_id": run_id, "step_order": order, "retries": one.get("retries")},
            )

        plan_elapsed = time.monotonic() - t_plan0
        confidence = _compute_confidence(
            steps_out, total_time_s=plan_elapsed, total_retries=total_retries_all
        )

        if session is not None and run_row is not None:
            target_state = LIFECYCLE_COMPLETED
            if stopped_early:
                reason = str(stopped_early.get("reason") or "")
                if reason in ("medium_risk_batch_confirm_required", "high_risk_requires_explicit_ok"):
                    run_row.status = "awaiting_confirmation"
                else:
                    run_row.status = "failed"
                    target_state = LIFECYCLE_FAILED
            else:
                run_row.status = "completed"
            rmeta = dict(run_row.meta_json or {})
            allowed, updated_meta, current = transition_lifecycle_state(
                meta_json=rmeta,
                next_state=target_state,
                transition_name=f"running_to_{target_state}_by_execute_action_plan",
            )
            if allowed:
                rmeta = updated_meta
            else:
                rmeta["lifecycle_transition_rejected"] = {"from": current, "to": target_state, "at": _now().isoformat()}
            rmeta["last_confidence"] = confidence
            run_row.meta_json = rmeta
            run_row.updated_at = _now()
            session.flush()

        all_step_ok = all(bool(s.get("ok")) for s in steps_out) if steps_out else (stopped_early is None)
        out: dict[str, Any] = {
            "ok": (stopped_early is None) and all_step_ok,
            "partial": (stopped_early is None) and bool(steps_out) and (not all_step_ok),
            "steps": steps_out,
            "stopped": stopped_early,
            "run_id": run_id,
            "confidence": confidence,
        }
        if session is not None:
            session.commit()
        return out
    except Exception as exc:  # pragma: no cover
        if session is not None:
            session.rollback()
        return {"ok": False, "error": str(exc), "steps": steps_out}
    finally:
        if session_cm is not None:
            session_cm.__exit__(None, None, None)


def plan_safety_preview(*, user_id: int, command: str, plan: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-step risk classification (shared by orchestration and persisted run creation)."""
    sc = str(command)[:8000]
    tr = get_system_trust_score(int(user_id))
    max_r = 0
    pre: list[dict[str, Any]] = []
    for row in plan:
        pr = classify_action_step(
            str(row.get("step_kind") or ""),
            str(row.get("risk_level") or "medium"),
            source_command=sc,
        )
        ts = int(apply_trust_damping(int(pr.get("risk_score") or 0), tr))
        if str(row.get("step_kind") or "") not in INTERNAL_SAFETY_ALWAYS_AUTO:
            max_r = max(max_r, ts)
        pre.append(
            {
                "step_order": int(row.get("step_order") or 0),
                "category": str(pr.get("category") or ""),
                "risk_score": ts,
                "approval_tier": str(approval_tier_from_score(ts)),
            }
        )
    return {"max_risk_score": max_r, "steps": pre}


def preflight_plan_execution_safety(
    *,
    user_id: int,
    intent: str,
    command: str,
    plan_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Full safety gate before any persisted run is created or executed via ``brain_execute``:

    * ``global_autonomy_halted`` / governance ``validate_action`` (``brain_execute`` + each ``action_layer_step``)
    * ``classify_action_step`` (with trust damping) per step
    * ``check_risk_budget`` per non-internal step
    * ``pre_execution_simulation_gate`` from aggregate max risk

    Returns ``preflight_by_order`` for run meta so ``execute_action_plan`` can skip
    duplicate classify / governance / budget for the same run only.
    """
    if global_autonomy_halted():
        return {
            "allowed": False,
            "reason": "global_autonomy_halt",
            "blocked_step_order": None,
            "governance": None,
            "preview_steps": [],
            "max_risk_score": 0,
            "preflight_by_order": {},
            "simulation": None,
        }
    sc = str(command or "").strip()[:8000]
    if not plan_steps:
        return {
            "allowed": False,
            "reason": "empty_plan",
            "blocked_step_order": None,
            "governance": None,
            "preview_steps": [],
            "max_risk_score": 0,
            "preflight_by_order": {},
            "simulation": None,
        }

    gov_brain = validate_action(
        "brain_execute",
        {
            "user_id": int(user_id),
            "domain": "automation",
            "payload": {
                "intent": str(intent or "unknown"),
                "step_count": len(plan_steps),
                "command_preview": sc[:500],
            },
        },
    )
    if not gov_brain.get("allowed"):
        return {
            "allowed": False,
            "reason": str(gov_brain.get("reason") or "governance_blocked"),
            "blocked_step_order": None,
            "governance": gov_brain,
            "preview_steps": [],
            "max_risk_score": 0,
            "preflight_by_order": {},
            "simulation": None,
        }

    tr = get_system_trust_score(int(user_id))
    max_r = 0
    preview_steps: list[dict[str, Any]] = []
    preflight_by_order: dict[str, dict[str, Any]] = {}

    for spec in sorted(plan_steps, key=lambda x: int(x.get("step_order") or 0)):
        order = int(spec.get("step_order") or 0)
        step_kind = str(spec.get("step_kind") or "")
        risk = str(spec.get("risk_level") or "medium").lower()

        pro = classify_action_step(step_kind, risk, source_command=sc)
        t_score = int(apply_trust_damping(int(pro.get("risk_score") or 0), tr))
        if step_kind in INTERNAL_SAFETY_ALWAYS_AUTO:
            eff_tier: str = "auto"
            risk_for_budget = 0
        else:
            eff_tier = str(approval_tier_from_score(t_score))
            risk_for_budget = t_score
            max_r = max(max_r, t_score)

        rbud = check_risk_budget(int(user_id), risk_for_budget)
        if not rbud.get("allowed"):
            return {
                "allowed": False,
                "reason": str(rbud.get("reason") or "risk_budget"),
                "blocked_step_order": order,
                "governance": None,
                "preview_steps": preview_steps,
                "max_risk_score": max_r,
                "preflight_by_order": preflight_by_order,
                "simulation": None,
            }

        gov = validate_action(
            "action_layer_step",
            {
                "user_id": int(user_id),
                "domain": "automation",
                "payload": {
                    "run_id": None,
                    "step_kind": step_kind,
                    "risk_level": risk,
                    "safety_risk_score": t_score,
                },
            },
        )
        if not gov.get("allowed") and str(gov.get("reason") or "") == "Database unavailable":
            if risk == "low" and (
                step_kind.startswith("internal_")
                or step_kind in {"plugin_notify", "plugin_file", "internal_summarize"}
            ):
                gov = {"ok": True, "allowed": True}
        if not gov.get("allowed"):
            return {
                "allowed": False,
                "reason": str(gov.get("reason") or "governance_blocked"),
                "blocked_step_order": order,
                "governance": gov,
                "preview_steps": preview_steps,
                "max_risk_score": max_r,
                "preflight_by_order": preflight_by_order,
                "simulation": None,
            }

        preview_steps.append(
            {
                "step_order": order,
                "category": str(pro.get("category") or ""),
                "risk_score": t_score,
                "approval_tier": eff_tier,
            }
        )
        preflight_by_order[str(order)] = {
            "tier": eff_tier,
            "risk_score": t_score,
            "category": str(pro.get("category") or ""),
        }

    sim = pre_execution_simulation_gate(int(user_id), source_command=sc, max_step_risk=int(max_r))
    if not sim.get("ok"):
        return {
            "allowed": False,
            "reason": str(sim.get("error") or sim.get("reason") or "simulation_failed"),
            "blocked_step_order": None,
            "governance": None,
            "preview_steps": preview_steps,
            "max_risk_score": max_r,
            "preflight_by_order": preflight_by_order,
            "simulation": sim,
        }
    if not sim.get("proceed", True) and not sim.get("skipped"):
        return {
            "allowed": False,
            "reason": "simulation_insufficient",
            "blocked_step_order": None,
            "governance": None,
            "preview_steps": preview_steps,
            "max_risk_score": max_r,
            "preflight_by_order": preflight_by_order,
            "simulation": sim,
        }

    return {
        "allowed": True,
        "reason": "",
        "blocked_step_order": None,
        "governance": gov_brain,
        "preview_steps": preview_steps,
        "max_risk_score": max_r,
        "preflight_by_order": preflight_by_order,
        "simulation": sim,
    }


def create_action_execution_run(
    *,
    user_id: int,
    organization_id: int,
    command: str,
    continuity_goal_id: int | None = None,
    plan_steps: list[dict[str, Any]] | None = None,
    preflight_extras: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    factory = _session_factory_or_none()
    if factory is None:
        return None
    plan = list(plan_steps) if plan_steps is not None else build_plan_steps_from_command(command)
    if not plan:
        return None
    meta: dict[str, Any] = {"batch_medium_ok": False, **(preflight_extras or {})}
    meta = _ensure_run_observability_meta(meta)
    timeline = dict(meta.get("lifecycle_timeline") or {})
    timeline["created_at"] = _iso_now()
    meta["lifecycle_timeline"] = timeline
    if continuity_goal_id:
        meta["continuity_goal_id"] = int(continuity_goal_id)
    sc = str(command)[:8000]
    preview = plan_safety_preview(user_id=int(user_id), command=sc, plan=plan)
    max_r = int(preview.get("max_risk_score") or 0)
    pre = list(preview.get("steps") or [])
    with factory() as session:
        run = ActionExecutionRun(
            user_id=int(user_id),
            organization_id=int(organization_id),
            source_command=sc,
            status="planned",
            meta_json=meta,
            continuity_goal_id=int(continuity_goal_id) if continuity_goal_id else None,
        )
        session.add(run)
        session.flush()
        for row in plan:
            session.add(
                ActionExecutionStep(
                    run_id=int(run.id),
                    step_order=int(row["step_order"]),
                    phase=str(row["phase"]),
                    step_kind=str(row["step_kind"]),
                    risk_level=str(row["risk_level"]),
                    status="pending",
                    payload_json=dict(row.get("payload") or {}),
                    result_json={},
                )
            )
        session.commit()
        out = get_action_execution_run(run_id=int(run.id), user_id=int(user_id))
        if out is not None:
            out = {**out, "safety_preview": {"max_risk_score": max_r, "steps": pre}}
        return out


def get_action_execution_run(*, run_id: int, user_id: int) -> dict[str, Any] | None:
    factory = _session_factory_or_none()
    if factory is None:
        return None
    with factory() as session:
        run = session.execute(
            select(ActionExecutionRun)
            .options(selectinload(ActionExecutionRun.steps))
            .where(ActionExecutionRun.id == int(run_id), ActionExecutionRun.user_id == int(user_id))
        ).scalar_one_or_none()
        if run is None:
            return None
        steps = sorted(run.steps, key=lambda s: (s.step_order, s.id))
        meta = _ensure_run_observability_meta(run.meta_json if isinstance(run.meta_json, dict) else {})
        closure = meta.get("execution_closure") if isinstance(meta.get("execution_closure"), dict) else {}
        auto_retry = meta.get("auto_retry") if isinstance(meta.get("auto_retry"), dict) else {}
        life = meta.get("lifecycle") if isinstance(meta.get("lifecycle"), dict) else {}
        return {
            "run_id": int(run.id),
            "organization_id": int(run.organization_id),
            "source_command": str(run.source_command or ""),
            "status": str(run.status or ""),
            "lifecycle_state": lifecycle_from_action_run(
                run_status=str(run.status or ""),
                meta_json=meta,
            ),
            "execution_trace_id": str(meta.get("execution_trace_id") or ""),
            "lifecycle_timeline": dict(meta.get("lifecycle_timeline") or {}),
            "retry_history": list(meta.get("retry_history") or []),
            "closure_history": list(meta.get("closure_history") or []),
            "last_transition": str(life.get("last_transition") or ""),
            "retry_count": int(auto_retry.get("count") or 0),
            "closure_status": str(closure.get("final_status") or "pending"),
            "continuity_goal_id": int(run.continuity_goal_id) if run.continuity_goal_id is not None else None,
            "meta_json": meta,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
            "steps": [
                {
                    "id": int(s.id),
                    "step_order": int(s.step_order),
                    "phase": str(s.phase),
                    "step_kind": str(s.step_kind),
                    "risk_level": str(s.risk_level),
                    "status": str(s.status),
                    "payload": s.payload_json or {},
                    "result": s.result_json or {},
                    "retry_count": int(s.retry_count or 0),
                    "explicit_confirmed_at": s.explicit_confirmed_at.isoformat() if s.explicit_confirmed_at else None,
                }
                for s in steps
            ],
        }


def confirm_action_execution_run(
    *,
    run_id: int,
    user_id: int,
    approve_batch_medium: bool = False,
    explicit_step_ids: list[int] | None = None,
) -> dict[str, Any] | None:
    factory = _session_factory_or_none()
    if factory is None:
        return None
    explicit_step_ids = explicit_step_ids or []
    with factory() as session:
        run = session.execute(
            select(ActionExecutionRun).where(ActionExecutionRun.id == int(run_id), ActionExecutionRun.user_id == int(user_id))
        ).scalar_one_or_none()
        if run is None:
            return None
        meta = dict(run.meta_json or {})
        if approve_batch_medium:
            meta["batch_medium_ok"] = True
        run.meta_json = meta
        if approve_batch_medium:
            stuck = (
                session.execute(
                    select(ActionExecutionStep).where(
                        ActionExecutionStep.run_id == int(run_id),
                        ActionExecutionStep.risk_level == "medium",
                        ActionExecutionStep.status == "awaiting_confirmation",
                    )
                )
                .scalars()
                .all()
            )
            for s in stuck:
                s.status = "pending"
        if explicit_step_ids:
            rows = (
                session.execute(
                    select(ActionExecutionStep).where(
                        ActionExecutionStep.run_id == int(run_id),
                        ActionExecutionStep.id.in_([int(x) for x in explicit_step_ids]),
                    )
                )
                .scalars()
                .all()
            )
            now = _now()
            for s in rows:
                if str(s.risk_level or "").lower() == "high":
                    s.explicit_confirmed_at = now
                    if str(s.status or "") == "awaiting_confirmation":
                        s.status = "pending"
        run.updated_at = _now()
        session.commit()
    return get_action_execution_run(run_id=int(run_id), user_id=int(user_id))


def cancel_action_execution_run(*, run_id: int, user_id: int) -> dict[str, Any] | None:
    """User interrupt: mark run cancelled; pending/awaiting steps become skipped (no real execution)."""
    factory = _session_factory_or_none()
    if factory is None:
        return None
    with factory() as session:
        run = session.execute(
            select(ActionExecutionRun).where(
                ActionExecutionRun.id == int(run_id), ActionExecutionRun.user_id == int(user_id)
            )
        ).scalar_one_or_none()
        if run is None:
            return None
        if str(run.status or "") in ("cancelled", "completed"):
            return get_action_execution_run(run_id=int(run_id), user_id=int(user_id))
        run.status = "cancelled"
        m = _ensure_run_observability_meta(run.meta_json if isinstance(run.meta_json, dict) else {})
        allowed, updated_meta, current = transition_lifecycle_state(
            meta_json=m,
            next_state=LIFECYCLE_CANCELLED,
            transition_name="running_to_cancelled_by_user",
        )
        if allowed:
            m = updated_meta
        else:
            m["lifecycle_transition_rejected"] = {"from": current, "to": LIFECYCLE_CANCELLED, "at": _now().isoformat()}
        m["cancelled_by_user"] = True
        m["cancelled_at"] = _now().isoformat()
        run.meta_json = m
        run.updated_at = _now()
        for s in (
            session.execute(select(ActionExecutionStep).where(ActionExecutionStep.run_id == int(run_id)))
            .scalars()
            .all()
        ):
            st = str(s.status or "")
            if st in ("pending", "awaiting_confirmation", "running"):
                s.status = "skipped"
                s.result_json = {"ok": False, "cancelled": True, "reason": "user_interrupt"}
        session.commit()
    return get_action_execution_run(run_id=int(run_id), user_id=int(user_id))


def run_persisted_action_plan(*, run_id: int, ctx: ActionExecutionContext) -> dict[str, Any]:
    """Load persisted steps and feed them to ``execute_action_plan``."""
    if global_autonomy_halted():
        return {"ok": False, "error": "global_autonomy_halt", "run_id": int(run_id)}
    payload = get_action_execution_run(run_id=int(run_id), user_id=int(ctx.user_id))
    if payload is None:
        return {"ok": False, "error": "run not found"}
    st = str(payload.get("status") or "")
    if st == "cancelled":
        return {"ok": False, "error": "run_cancelled", "run_id": int(run_id)}

    src = str(payload.get("source_command") or "")
    meta0 = payload.get("meta_json") if isinstance(payload.get("meta_json"), dict) else {}
    brain_pf = bool(meta0.get("brain_safety_preflight_v1"))
    preflight_by_order = meta0.get("preflight_by_order") if isinstance(meta0.get("preflight_by_order"), dict) else {}

    if brain_pf:
        max_r = int(meta0.get("preflight_max_risk_score") or 0)
        sim: dict[str, Any] = {
            "ok": True,
            "proceed": True,
            "skipped": True,
            "reason": "brain_safety_preflight_v1",
        }
    else:
        max_r = 0
        for s in payload.get("steps") or []:
            pr = classify_action_step(
                str(s.get("step_kind") or ""),
                str(s.get("risk_level") or "medium"),
                source_command=src,
            )
            tsi = int(
                apply_trust_damping(
                    int(pr.get("risk_score") or 0), get_system_trust_score(int(ctx.user_id))
                )
            )
            if str(s.get("step_kind") or "") in INTERNAL_SAFETY_ALWAYS_AUTO:
                continue
            max_r = max(max_r, tsi)
        sim = pre_execution_simulation_gate(
            int(ctx.user_id), source_command=src, max_step_risk=int(max_r)
        )
        if not sim.get("ok"):
            return {"ok": False, "error": "simulation_failed", "simulation": sim, "run_id": int(run_id)}
        if not sim.get("proceed", True) and not sim.get("skipped"):
            return {
                "ok": False,
                "error": "simulation_gate",
                "stopped": {
                    "reason": "simulation_insufficient",
                    "success_probability": sim.get("success_probability"),
                    "threshold": sim.get("threshold"),
                },
                "run_id": int(run_id),
            }
    factory = _session_factory_or_none()
    if factory is None:
        return {"ok": False, "error": "database unavailable"}
    with factory() as session:
        run = session.execute(
            select(ActionExecutionRun).where(ActionExecutionRun.id == int(run_id), ActionExecutionRun.user_id == int(ctx.user_id))
        ).scalar_one_or_none()
        if run is None:
            return {"ok": False, "error": "run not found"}
        if str(run.status or "") == "cancelled":
            return {"ok": False, "error": "run_cancelled", "run_id": int(run_id)}
        m = dict(run.meta_json or {})
        allowed, updated_meta, current = transition_lifecycle_state(
            meta_json=m,
            next_state=LIFECYCLE_RUNNING,
            transition_name="retrying_to_running_by_run_start",
        )
        if allowed:
            m = updated_meta
        else:
            m["lifecycle_transition_rejected"] = {"from": current, "to": LIFECYCLE_RUNNING, "at": _now().isoformat()}
        timeline = dict(m.get("lifecycle_timeline") or {})
        if not timeline.get("started_at"):
            timeline["started_at"] = _iso_now()
        timeline["last_step_at"] = _iso_now()
        m["lifecycle_timeline"] = timeline
        m["safety_prestep_sim"] = {k: sim.get(k) for k in ("proceed", "success_probability", "path", "skipped", "reason") if k in sim}
        run.meta_json = m
        run.status = "running"
        run.updated_at = _now()
        session.commit()

    plan_steps: list[dict[str, Any]] = []
    for s in payload.get("steps") or []:
        plan_steps.append(
            {
                "step_order": int(s.get("step_order") or 0),
                "phase": str(s.get("phase") or ""),
                "step_kind": str(s.get("step_kind") or ""),
                "risk_level": str(s.get("risk_level") or "medium"),
                "payload": s.get("payload") if isinstance(s.get("payload"), dict) else {},
            }
        )
    return execute_action_plan(
        plan_steps,
        ctx=ctx,
        run_id=int(run_id),
        brain_safety_preflight=brain_pf,
        preflight_by_order=preflight_by_order if brain_pf else None,
    )


def action_plan_execute_worker(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = int(payload.get("run_id") or 0)
    uid = int(payload.get("user_id") or 0)
    oid = int(payload.get("organization_id") or 0)
    role = str(payload.get("role_name") or "")
    if run_id <= 0 or uid <= 0 or oid <= 0:
        return {"ok": False, "error": "run_id, user_id, organization_id required"}
    payload_run = get_action_execution_run(run_id=run_id, user_id=uid)
    cmd = str((payload_run or {}).get("source_command") or "").strip()
    if not cmd:
        return {"ok": False, "error": "run source_command not found", "run_id": int(run_id)}
    from services.brain_execute import brain_execute

    _ = role
    out = brain_execute(command=cmd, user_id=uid, organization_id=oid)
    return {
        "ok": bool(((out.get("result") if isinstance(out, dict) else {}) or {}).get("ok", True)),
        "run_id": int(
            ((out.get("result") if isinstance(out, dict) else {}) or {}).get("run_id")
            or out.get("run_id")
            or 0
        ),
        "status": str(out.get("status") or ""),
        "routed_via": "brain_execute",
        "parent_run_id": int(run_id),
        "result": out,
    }
