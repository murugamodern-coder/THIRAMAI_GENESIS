"""Autonomous continuity: persistent goals, environment-aware scheduling, action execution, LTM binding."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from core.database import get_session_factory
from core.db.models import ContinuityGoal, ContinuityUserSettings
from services.brain_execute import brain_execute
from services.governance_engine import log_execution, validate_action
from services.long_term_memory_engine import evolve_plan_with_memory, store_agent_episode
from services.task_decomposition import build_plan_steps_from_command

_ALLOWED_LEVELS = frozenset({"observe", "assist", "semi_auto", "full_auto"})


def _session():
    return get_session_factory()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_level(raw: str | None) -> str:
    s = str(raw or "assist").strip().lower()
    return s if s in _ALLOWED_LEVELS else "assist"


def get_or_create_settings(*, user_id: int, organization_id: int) -> dict[str, Any]:
    factory = _session()
    if factory is None:
        return {
            "autonomy_level": "assist",
            "enabled": False,
            "time_budget_minutes_per_day": 120,
            "capital_budget": 0.0,
            "effort_budget": 10,
            "allow_auto_batch_medium": False,
            "runs_today": 0,
            "last_tick_at": None,
            "meta_json": {},
        }
    with factory() as session:
        row = session.execute(
            select(ContinuityUserSettings).where(
                ContinuityUserSettings.user_id == int(user_id),
                ContinuityUserSettings.organization_id == int(organization_id),
            )
        ).scalar_one_or_none()
        if row is None:
            row = ContinuityUserSettings(
                user_id=int(user_id),
                organization_id=int(organization_id),
                autonomy_level="assist",
                enabled=False,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
        return {
            "id": int(row.id),
            "autonomy_level": _coerce_level(row.autonomy_level),
            "enabled": bool(row.enabled),
            "time_budget_minutes_per_day": int(row.time_budget_minutes_per_day or 120),
            "capital_budget": float(row.capital_budget or 0.0),
            "effort_budget": int(row.effort_budget or 10),
            "allow_auto_batch_medium": bool(row.allow_auto_batch_medium),
            "runs_today": int(row.runs_today or 0),
            "last_tick_at": row.last_tick_at.isoformat() if row.last_tick_at else None,
            "meta_json": row.meta_json or {},
        }


def upsert_settings(
    *,
    user_id: int,
    organization_id: int,
    autonomy_level: str | None = None,
    enabled: bool | None = None,
    time_budget_minutes_per_day: int | None = None,
    capital_budget: float | None = None,
    effort_budget: int | None = None,
    allow_auto_batch_medium: bool | None = None,
) -> dict[str, Any] | None:
    factory = _session()
    if factory is None:
        return None
    with factory() as session:
        row = session.execute(
            select(ContinuityUserSettings).where(
                ContinuityUserSettings.user_id == int(user_id),
                ContinuityUserSettings.organization_id == int(organization_id),
            )
        ).scalar_one_or_none()
        if row is None:
            row = ContinuityUserSettings(user_id=int(user_id), organization_id=int(organization_id))
            session.add(row)
        if autonomy_level is not None:
            row.autonomy_level = _coerce_level(autonomy_level)
        if enabled is not None:
            row.enabled = bool(enabled)
        if time_budget_minutes_per_day is not None:
            row.time_budget_minutes_per_day = max(1, int(time_budget_minutes_per_day))
        if capital_budget is not None:
            row.capital_budget = float(capital_budget)
        if effort_budget is not None:
            row.effort_budget = max(1, int(effort_budget))
        if allow_auto_batch_medium is not None:
            row.allow_auto_batch_medium = bool(allow_auto_batch_medium)
        row.updated_at = _now()
        session.commit()
    return get_or_create_settings(user_id=int(user_id), organization_id=int(organization_id))


def list_goals(*, user_id: int, organization_id: int, statuses: list[str] | None = None) -> list[dict[str, Any]]:
    st = statuses or ["active", "interrupted", "waiting_action"]
    factory = _session()
    if factory is None:
        return []
    with factory() as session:
        q = select(ContinuityGoal).where(
            ContinuityGoal.user_id == int(user_id),
            ContinuityGoal.organization_id == int(organization_id),
            ContinuityGoal.status.in_(st),
        )
        rows = session.execute(q.order_by(ContinuityGoal.priority.asc(), ContinuityGoal.id.asc())).scalars().all()
        return [_goal_to_dict(r) for r in rows]


def _goal_to_dict(r: ContinuityGoal) -> dict[str, Any]:
    return {
        "id": int(r.id),
        "objective": str(r.objective or ""),
        "priority": int(r.priority or 3),
        "deadline": r.deadline.isoformat() if r.deadline else None,
        "status": str(r.status or ""),
        "progress_pct": float(r.progress_pct or 0.0),
        "steps_completed": int(r.steps_completed or 0),
        "total_steps_est": int(r.total_steps_est or 0),
        "remaining_actions": r.remaining_actions_json or {},
        "completed_steps": r.completed_steps_json or {},
        "meta_json": r.meta_json or {},
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def create_goal(
    *,
    user_id: int,
    organization_id: int,
    objective: str,
    priority: int = 3,
    deadline: datetime | None = None,
) -> dict[str, Any] | None:
    factory = _session()
    if not objective.strip() or factory is None:
        return None
    with factory() as session:
        g = ContinuityGoal(
            user_id=int(user_id),
            organization_id=int(organization_id),
            objective=str(objective).strip()[:20000],
            priority=max(1, min(5, int(priority))),
            deadline=deadline,
            status="active",
        )
        session.add(g)
        session.commit()
        session.refresh(g)
        return _goal_to_dict(g)


def update_goal(
    *,
    user_id: int,
    goal_id: int,
    objective: str | None = None,
    priority: int | None = None,
    deadline: datetime | None = None,
    clear_deadline: bool = False,
    status: str | None = None,
    progress_pct: float | None = None,
    total_steps_est: int | None = None,
    remaining_actions_json: dict[str, Any] | None = None,
    completed_steps_json: dict[str, Any] | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    factory = _session()
    if factory is None:
        return None
    with factory() as session:
        g = session.get(ContinuityGoal, int(goal_id))
        if g is None or g.user_id != int(user_id):
            return None
        if objective is not None:
            g.objective = str(objective).strip()[:20000] or g.objective
        if priority is not None:
            g.priority = max(1, min(5, int(priority)))
        if clear_deadline:
            g.deadline = None
        elif deadline is not None:
            g.deadline = deadline
        if status:
            g.status = str(status)[:32]
        if progress_pct is not None:
            g.progress_pct = max(0.0, min(100.0, float(progress_pct)))
        if total_steps_est is not None:
            g.total_steps_est = max(0, int(total_steps_est))
        if remaining_actions_json is not None:
            g.remaining_actions_json = remaining_actions_json
        if completed_steps_json is not None:
            g.completed_steps_json = completed_steps_json
        if extra_meta:
            m = dict(g.meta_json or {})
            m.update(extra_meta)
            g.meta_json = m
        g.updated_at = _now()
        session.commit()
        session.refresh(g)
        return _goal_to_dict(g)


def build_environment_context(*, user_id: int, organization_id: int) -> dict[str, Any]:
    now = _now()
    hours = int(now.timestamp() // 3600) % 24
    settings = get_or_create_settings(user_id=int(user_id), organization_id=int(organization_id))
    active = list_goals(user_id=int(user_id), organization_id=int(organization_id), statuses=["active", "interrupted"])
    pending_n = len(active)
    urgency = 0.0
    for g in active:
        dl = g.get("deadline")
        if dl:
            try:
                ddt = datetime.fromisoformat(dl.replace("Z", "+00:00"))
                if ddt < now:
                    urgency += 1.0
                else:
                    delta = (ddt - now).total_seconds() / 86400.0
                    if delta < 2:
                        urgency += 0.5
            except Exception:
                pass
    return {
        "time_utc": now.isoformat(),
        "local_hour_bucket": hours,
        "active_goals_count": pending_n,
        "urgency_score": min(3.0, urgency),
        "time_budget_minutes": settings.get("time_budget_minutes_per_day", 120),
        "effort_remaining": max(0, int(settings.get("effort_budget", 10)) - int(settings.get("meta_json", {}).get("effort_used_today", 0) or 0)),
    }


def score_goal_economics(goal: dict[str, Any], env: dict[str, Any], *, capital: float) -> float:
    """ROI-like score: higher = pick first. Priority 1 best; deadline pressure; low capital use."""
    p = 6.0 - float(int(goal.get("priority") or 3))
    prog = 1.0 - (float(goal.get("progress_pct") or 0) / 100.0)
    roi_hint = float((goal.get("meta_json") or {}).get("expected_roi", 0.5))
    risk = float((goal.get("meta_json") or {}).get("risk_score", 0.3))
    deadline_push = 1.0 + 0.2 * min(1.0, float(env.get("urgency_score") or 0))
    cap = max(0.1, 1.0 - min(0.4, float(capital) / 100000.0))
    return p * 2.0 + prog * 3.0 + roi_hint * 2.0 + deadline_push - risk * 1.5 + cap * 0.1


def _plan_has_high_risk(command: str) -> bool:
    plan = build_plan_steps_from_command(command)
    for s in plan:
        if str(s.get("risk_level") or "") == "high":
            return True
    return False


def _plan_needs_batch_medium(command: str) -> bool:
    plan = build_plan_steps_from_command(command)
    return any(str(s.get("risk_level") or "") == "medium" for s in plan)


def _maybe_reset_daily_runs(session, row: ContinuityUserSettings) -> None:
    m = dict(row.meta_json or {})
    today = date.today().isoformat()
    if m.get("runs_date") != today:
        row.runs_today = 0
        m["runs_date"] = today
        m["effort_used_today"] = 0
        row.meta_json = m


def _pop_goal_meta_keys(user_id: int, goal_id: int, keys: tuple[str, ...]) -> None:
    factory = _session()
    if not keys or factory is None:
        return
    with factory() as session:
        g = session.get(ContinuityGoal, int(goal_id))
        if g is None or g.user_id != int(user_id):
            return
        m = dict(g.meta_json or {})
        for k in keys:
            m.pop(k, None)
        g.meta_json = m
        g.updated_at = _now()
        session.commit()


def run_continuity_tick(user_id: int, organization_id: int, role_name: str = "owner") -> dict[str, Any]:
    """One scheduler/RQ tick: select goal, optional memory, create action run, execute per autonomy level."""
    factory = _session()
    if factory is None:
        return {"ok": False, "error": "database unavailable"}
    settings = get_or_create_settings(user_id=int(user_id), organization_id=int(organization_id))
    if not settings.get("enabled"):
        return {"ok": True, "skipped": True, "reason": "continuity disabled"}
    from services.autonomy_safety_layer import global_autonomy_halted

    if global_autonomy_halted():
        return {"ok": True, "skipped": True, "reason": "global autonomy halt"}

    gate = validate_action(
        "continuity_autonomous_tick",
        {"user_id": int(user_id), "domain": "automation", "payload": {"org": int(organization_id)}},
    )
    if not gate.get("allowed"):
        return {"ok": False, "blocked": True, "reason": gate.get("reason") or "governance"}

    with factory() as session:
        srow = session.execute(
            select(ContinuityUserSettings).where(
                ContinuityUserSettings.user_id == int(user_id),
                ContinuityUserSettings.organization_id == int(organization_id),
            )
        ).scalar_one_or_none()
        if srow is None:
            return {"ok": False, "error": "settings missing"}
        _maybe_reset_daily_runs(session, srow)
        max_r = int((os.getenv("THIRAMAI_CONTINUITY_MAX_RUNS_PER_DAY") or "12").strip() or "12")
        if int(srow.runs_today or 0) >= max(1, max_r):
            session.commit()
            return {"ok": True, "skipped": True, "reason": "daily run cap"}
        session.commit()

    goals = list_goals(
        user_id=int(user_id), organization_id=int(organization_id), statuses=["active", "interrupted", "waiting_action"]
    )
    if not goals:
        return {"ok": True, "skipped": True, "reason": "no active goals"}
    env = build_environment_context(user_id=int(user_id), organization_id=int(organization_id))
    capital = float(settings.get("capital_budget", 0.0))
    ranked = sorted(
        goals,
        key=lambda g: score_goal_economics(g, env, capital=capital),
        reverse=True,
    )
    goal = ranked[0]
    goal_id = int(goal["id"])

    mem = evolve_plan_with_memory(user_id=int(user_id), goal_id=goal_id, goal_context={"description": goal["objective"]})
    insights = " ".join((mem.get("memory_insights") or [])[:3])
    command = str(goal["objective"])
    if insights:
        command = f"{command}\n\nContext from memory: {insights[:500]}"

    if str(goal.get("status")) == "interrupted":
        ck = (goal.get("meta_json") or {}).get("interrupt_checkpoint") or {}
        if ck.get("resume_command"):
            command = str(ck["resume_command"])[:8000]
    mjson0 = goal.get("meta_json") or {}
    if mjson0.get("user_resume_command") and str(goal.get("status")) in (
        "active",
        "waiting_action",
    ):
        command = str(mjson0["user_resume_command"])[:8000]
        _pop_goal_meta_keys(
            int(user_id),
            goal_id,
            ("user_resume_command",),
        )

    level = str(settings.get("autonomy_level") or "assist")

    if level == "observe":
        with factory() as session_:
            g2 = session_.get(ContinuityGoal, goal_id)
            if g2 is not None:
                m = dict(g2.meta_json or {})
                m["last_suggestion"] = command[:4000]
                m["suggested_at"] = _now().isoformat()
                m["environment"] = env
                g2.meta_json = m
                g2.updated_at = _now()
            srow2 = session_.execute(
                select(ContinuityUserSettings).where(
                    ContinuityUserSettings.user_id == int(user_id),
                    ContinuityUserSettings.organization_id == int(organization_id),
                )
            ).scalar_one()
            srow2.last_tick_at = _now()
            session_.commit()
        log_execution(
            user_id=int(user_id),
            action_type="continuity_observe",
            source="continuity",
            payload_json={"goal_id": goal_id, "command_preview": command[:200]},
            result_json={"mode": "observe"},
            status="success",
            execution_id=f"cg_{goal_id}",
            reasoning_summary="Continuity engine observed; no action run created.",
            why_action_taken="autonomy_level=observe",
            data_influenced_json={},
        )
        return {"ok": True, "mode": "observe", "suggestion": command[:2000], "goal_id": goal_id}

    run_id = 0
    if level == "assist":
        with factory() as session_:
            srow2 = session_.execute(
                select(ContinuityUserSettings).where(
                    ContinuityUserSettings.user_id == int(user_id),
                    ContinuityUserSettings.organization_id == int(organization_id),
                )
            ).scalar_one()
            srow2.last_tick_at = _now()
            srow2.runs_today = int(srow2.runs_today or 0) + 1
            m = dict(srow2.meta_json or {})
            m["effort_used_today"] = int(m.get("effort_used_today", 0)) + 1
            srow2.meta_json = m
            g2 = session_.get(ContinuityGoal, goal_id)
            if g2 is not None:
                g2.status = "waiting_action"
                g2.meta_json = {**(g2.meta_json or {}), "suggested_command": command[:2000]}
                g2.updated_at = _now()
            session_.commit()
        return {
            "ok": True,
            "mode": "assist",
            "run_id": None,
            "goal_id": goal_id,
            "message": "Suggestion prepared; execution requires explicit command run through brain_execute.",
        }

    exec_out: dict[str, Any] = {}
    if level == "semi_auto":
        if _plan_has_high_risk(command):
            with factory() as session:
                g2 = session.get(ContinuityGoal, goal_id)
                if g2 is not None:
                    g2.status = "waiting_action"
                    g2.meta_json = {**(g2.meta_json or {}), "reason": "high_risk_needs_user"}
                    session.commit()
            return {"ok": True, "mode": "semi_auto", "run_id": None, "goal_id": goal_id, "waiting": "high_risk"}
        if _plan_needs_batch_medium(command) and not settings.get("allow_auto_batch_medium"):
            with factory() as session:
                g2 = session.get(ContinuityGoal, goal_id)
                if g2 is not None:
                    g2.status = "waiting_action"
                    g2.meta_json = {**(g2.meta_json or {})}
                    session.commit()
            return {"ok": True, "mode": "semi_auto", "run_id": None, "goal_id": goal_id, "waiting": "batch_medium"}
        exec_out = brain_execute(command=command, user_id=int(user_id), organization_id=int(organization_id))
    elif level == "full_auto":
        exec_out = brain_execute(command=command, user_id=int(user_id), organization_id=int(organization_id))

    run_id = int(
        ((exec_out.get("result") if isinstance(exec_out, dict) else {}) or {}).get("run_id")
        or exec_out.get("run_id")
        or 0
    )

    # Progress + LTM
    conf = (exec_out.get("confidence") or {}) if exec_out else {}
    if run_id > 0:
        _apply_goal_progress(goal_id, user_id, run_id, exec_out, None)
    try:
        store_agent_episode(
            user_id=int(user_id),
            execution_id=f"action_run_{run_id}" if run_id > 0 else f"continuity_exec_{goal_id}",
            goal_id=goal_id,
            outcome={"ok": exec_out.get("ok"), "confidence": conf, "continuity": True},
        )
    except Exception:
        pass

    with factory() as session:
        srow2 = session.execute(
            select(ContinuityUserSettings).where(
                ContinuityUserSettings.user_id == int(user_id),
                ContinuityUserSettings.organization_id == int(organization_id),
            )
        ).scalar_one()
        srow2.last_tick_at = _now()
        srow2.runs_today = int(srow2.runs_today or 0) + 1
        m = dict(srow2.meta_json or {})
        m["effort_used_today"] = int(m.get("effort_used_today", 0)) + 1
        srow2.meta_json = m
        session.commit()

    st_out = (exec_out.get("stopped") or {}) if isinstance(exec_out, dict) else {}
    if st_out.get("reason") in ("high_risk_requires_explicit_ok", "medium_risk_batch_confirm_required"):
        with factory() as session:
            g2 = session.get(ContinuityGoal, goal_id)
            if g2 is not None:
                g2.status = "interrupted"
                g2.meta_json = {
                    **(g2.meta_json or {}),
                    "interrupt_checkpoint": {
                        "run_id": run_id,
                        "reason": st_out.get("reason"),
                        "resume_command": command,
                    },
                }
                g2.updated_at = _now()
            session.commit()

    log_execution(
        user_id=int(user_id),
        action_type="continuity_tick",
        source="continuity",
        payload_json={"goal_id": goal_id, "run_id": run_id, "level": level},
        result_json=exec_out if isinstance(exec_out, dict) else {},
        status="success" if (exec_out or {}).get("ok", True) else "failed",
        execution_id=f"cg_{goal_id}",
        reasoning_summary="Continuity engine tick executed action plan for top goal.",
        why_action_taken=f"autonomy_level={level}",
        data_influenced_json={"goal": goal.get("objective", "")[:120]},
    )
    return {"ok": True, "goal_id": goal_id, "run_id": run_id, "action_result": exec_out, "autonomy_level": level}


def _apply_goal_progress(
    goal_id: int,
    user_id: int,
    run_id: int,
    exec_out: dict[str, Any],
    gpayload: dict[str, Any] | None,
) -> None:
    factory = _session()
    if factory is None:
        return
    steps = (exec_out or {}).get("steps") or []
    okn = sum(1 for s in steps if s.get("ok") is True)
    total = max(1, len(steps))
    part = 100.0 * okn / float(total)
    with factory() as session:
        g = session.get(ContinuityGoal, int(goal_id))
        if g is None or g.user_id != int(user_id):
            return
        g.progress_pct = min(100.0, max(float(g.progress_pct or 0), part * 0.5 + float(g.progress_pct or 0) * 0.5))
        g.steps_completed = int(g.steps_completed or 0) + okn
        m = dict(g.meta_json or {})
        hist = list(m.get("execution_history", []))[-19:]
        hist.append(
            {
                "run_id": run_id,
                "at": _now().isoformat(),
                "ok": (exec_out or {}).get("ok"),
                "confidence": (exec_out or {}).get("confidence"),
            }
        )
        m["execution_history"] = hist
        g.meta_json = m
        g.updated_at = _now()
        if (exec_out or {}).get("ok") and not (exec_out or {}).get("partial") and (exec_out or {}).get("confidence", {}).get("score", 0) > 0.85:
            g.status = "completed" if g.progress_pct >= 99.0 else g.status
        session.commit()


def mark_goal_interrupted(*, user_id: int, goal_id: int, run_id: int | None) -> dict[str, Any] | None:
    return update_goal(
        user_id=int(user_id),
        goal_id=int(goal_id),
        status="interrupted",
        extra_meta={"interrupt_run": run_id} if run_id is not None else {"note": "interrupted"},
    )


def resume_continuity_goal(
    *,
    user_id: int,
    goal_id: int,
    resume_command: str | None = None,
) -> dict[str, Any] | None:
    """Clear interrupt checkpoint, optionally set a new command, set status to active for next tick."""
    factory = _session()
    if factory is None:
        return None
    with factory() as session:
        g = session.get(ContinuityGoal, int(goal_id))
        if g is None or g.user_id != int(user_id):
            return None
        m = dict(g.meta_json or {})
        m.pop("interrupt_checkpoint", None)
        m.pop("interrupt_run", None)
        m["resumed_at"] = _now().isoformat()
        if resume_command and str(resume_command).strip():
            m["user_resume_command"] = str(resume_command).strip()[:8000]
        g.meta_json = m
        g.status = "active"
        g.updated_at = _now()
        session.commit()
        session.refresh(g)
        return _goal_to_dict(g)


def continuity_worker(payload: dict[str, Any]) -> dict[str, Any]:
    return run_continuity_tick(
        int(payload.get("user_id") or 0),
        int(payload.get("organization_id") or 0),
        str(payload.get("role_name") or "owner"),
    )
