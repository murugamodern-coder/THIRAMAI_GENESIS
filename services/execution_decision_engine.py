"""
Single execution authority arbitration layer.

Collects candidates from intent/autonomous/value sources and executes at most one action.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import ActionExecutionRun, DomainDominionProfile
from core.observability import log_structured
from services.autonomy_governor_engine import compute_autonomy_decision
from services.feedback_engine import calculate_prediction_accuracy
from services.meta_autonomy_engine import monitor_system_performance

SOURCE_PRIORITY = {"intent_execution": 0, "autonomous_action": 1, "value_execution": 2}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _score(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except Exception:
        x = float(default)
    return max(0.0, min(1.0, x))


def _to_text(v: Any, n: int = 260) -> str:
    return str(v or "").strip().replace("\n", " ")[:n]


def _validate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {"ok": False, "reason": "invalid_schema"}
    required_fields: dict[str, type] = {
        "source": str,
        "command": str,
        "confidence": float,
        "risk": float,
        "mission_alignment": float,
    }
    for field, expected_type in required_fields.items():
        if field not in candidate:
            return {"ok": False, "reason": f"missing_field:{field}"}
        value = candidate.get(field)
        if expected_type is str:
            if not isinstance(value, str):
                return {"ok": False, "reason": f"invalid_type:{field}"}
            if not str(value).strip():
                return {"ok": False, "reason": f"missing_field:{field}"}
            continue
        try:
            float(value)
        except Exception:
            return {"ok": False, "reason": f"invalid_type:{field}"}
    for optional_num in ("priority_score",):
        if optional_num in candidate and candidate.get(optional_num) is not None:
            try:
                float(candidate.get(optional_num))
            except Exception:
                return {"ok": False, "reason": f"invalid_type:{optional_num}"}
    for optional_bool in ("safe_to_execute", "assist_required"):
        if optional_bool in candidate and candidate.get(optional_bool) is not None and not isinstance(candidate.get(optional_bool), bool):
            return {"ok": False, "reason": f"invalid_type:{optional_bool}"}
    return {"ok": True}


def _decision_score(c: dict[str, Any]) -> float:
    confidence = _score(c.get("confidence"), 0.0)
    mission_alignment = _score(c.get("mission_alignment"), 0.0)
    risk = _score(c.get("risk"), 1.0)
    priority_score = _score(c.get("priority_score"), 0.0)
    return round(
        (0.30 * confidence) + (0.30 * mission_alignment) + (0.20 * (1.0 - risk)) + (0.20 * priority_score),
        6,
    )


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _parse_iso(ts: Any) -> datetime | None:
    raw = str(ts or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_state(*, user_id: int, organization_id: int) -> dict[str, Any]:
    fn = _session_factory_or_none()
    if fn is None:
        return {"cooldown_until": None, "failure_backoff_until": None, "recent": []}
    with fn() as session:
        row = session.execute(
            select(DomainDominionProfile).where(
                DomainDominionProfile.user_id == int(user_id),
                DomainDominionProfile.organization_id == int(organization_id),
            )
        ).scalar_one_or_none()
        if row is None:
            return {"cooldown_until": None, "failure_backoff_until": None, "recent": []}
        meta = dict(row.meta_json or {})
        st = meta.get("execution_decision_state") if isinstance(meta.get("execution_decision_state"), dict) else {}
        return {
            "cooldown_until": st.get("cooldown_until"),
            "failure_backoff_until": st.get("failure_backoff_until"),
            "recent": list(st.get("recent") or []),
        }


def _save_state(
    *,
    user_id: int,
    organization_id: int,
    cooldown_until: datetime | None,
    failure_backoff_until: datetime | None,
    recent_append: dict[str, Any],
) -> None:
    fn = _session_factory_or_none()
    if fn is None:
        return
    with fn() as session:
        row = session.execute(
            select(DomainDominionProfile).where(
                DomainDominionProfile.user_id == int(user_id),
                DomainDominionProfile.organization_id == int(organization_id),
            )
        ).scalar_one_or_none()
        if row is None:
            return
        meta = dict(row.meta_json or {})
        st = meta.get("execution_decision_state") if isinstance(meta.get("execution_decision_state"), dict) else {}
        rec = list(st.get("recent") or [])
        rec.append(recent_append)
        st["recent"] = rec[-120:]
        st["cooldown_until"] = cooldown_until.isoformat() if isinstance(cooldown_until, datetime) else None
        st["failure_backoff_until"] = failure_backoff_until.isoformat() if isinstance(failure_backoff_until, datetime) else None
        meta["execution_decision_state"] = st
        row.meta_json = meta
        row.updated_at = _now()
        session.commit()


def _acquire_execution_lease(*, user_id: int, organization_id: int, lease_seconds: int = 120) -> dict[str, Any]:
    fn = _session_factory_or_none()
    if fn is None:
        return {"ok": False, "reason": "database_unavailable"}
    token = str(uuid4())
    now = _now()
    with fn() as session:
        row = session.execute(
            select(DomainDominionProfile)
            .where(
                DomainDominionProfile.user_id == int(user_id),
                DomainDominionProfile.organization_id == int(organization_id),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            return {"ok": False, "reason": "profile_missing"}
        meta = dict(row.meta_json or {})
        st = meta.get("execution_decision_state") if isinstance(meta.get("execution_decision_state"), dict) else {}
        lease = st.get("lease") if isinstance(st.get("lease"), dict) else {}
        until = _parse_iso(lease.get("expires_at"))
        if until and until > now and str(lease.get("token") or "").strip():
            return {"ok": False, "reason": "lease_active", "lease_expires_at": until.isoformat()}
        st["lease"] = {"token": token, "acquired_at": now.isoformat(), "expires_at": (now + timedelta(seconds=max(30, int(lease_seconds)))).isoformat()}
        meta["execution_decision_state"] = st
        row.meta_json = meta
        row.updated_at = now
        session.commit()
    return {"ok": True, "token": token}


def _finalize_with_lease(
    *,
    user_id: int,
    organization_id: int,
    lease_token: str,
    cooldown_until: datetime | None,
    failure_backoff_until: datetime | None,
    recent_append: dict[str, Any],
) -> bool:
    fn = _session_factory_or_none()
    if fn is None:
        return False
    with fn() as session:
        row = session.execute(
            select(DomainDominionProfile)
            .where(
                DomainDominionProfile.user_id == int(user_id),
                DomainDominionProfile.organization_id == int(organization_id),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            return False
        meta = dict(row.meta_json or {})
        st = meta.get("execution_decision_state") if isinstance(meta.get("execution_decision_state"), dict) else {}
        lease = st.get("lease") if isinstance(st.get("lease"), dict) else {}
        if str(lease.get("token") or "") != str(lease_token):
            return False
        rec = list(st.get("recent") or [])
        rec.append(recent_append)
        st["recent"] = rec[-120:]
        st["cooldown_until"] = cooldown_until.isoformat() if isinstance(cooldown_until, datetime) else None
        st["failure_backoff_until"] = failure_backoff_until.isoformat() if isinstance(failure_backoff_until, datetime) else None
        st["lease"] = {}
        meta["execution_decision_state"] = st
        row.meta_json = meta
        row.updated_at = _now()
        session.commit()
    return True


def _release_lease(*, user_id: int, organization_id: int, lease_token: str) -> None:
    fn = _session_factory_or_none()
    if fn is None:
        return
    with fn() as session:
        row = session.execute(
            select(DomainDominionProfile)
            .where(
                DomainDominionProfile.user_id == int(user_id),
                DomainDominionProfile.organization_id == int(organization_id),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            return
        meta = dict(row.meta_json or {})
        st = meta.get("execution_decision_state") if isinstance(meta.get("execution_decision_state"), dict) else {}
        lease = st.get("lease") if isinstance(st.get("lease"), dict) else {}
        if str(lease.get("token") or "") != str(lease_token):
            return
        st["lease"] = {}
        meta["execution_decision_state"] = st
        row.meta_json = meta
        row.updated_at = _now()
        session.commit()


def _normalize_candidates(
    *,
    intent_execution: dict[str, Any] | None,
    autonomous_actions: dict[str, Any] | None,
    value_execution: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    out: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []

    def add(rows: list[dict[str, Any]], default_source: str) -> None:
        for r in rows:
            if not isinstance(r, dict):
                invalid.append({"reason": "invalid_schema", "candidate": {"source": default_source}})
                continue
            raw = {
                "source": r.get("source") if r.get("source") is not None else default_source,
                "command": r.get("command"),
                "confidence": r.get("confidence"),
                "risk": r.get("risk"),
                "mission_alignment": r.get("mission_alignment"),
                "priority_score": r.get("priority_score", 0.0),
                "safe_to_execute": r.get("safe_to_execute", True),
                "assist_required": r.get("assist_required", False),
                "title": r.get("title", ""),
            }
            verdict = _validate_candidate(raw)
            if not bool(verdict.get("ok")):
                invalid.append({"reason": str(verdict.get("reason") or "invalid_schema"), "candidate": {"source": default_source, "title": _to_text(r.get("title"), 200)}})
                continue
            out.append(
                {
                    "source": str(raw.get("source")),
                    "command": _to_text(raw.get("command"), 1200),
                    "confidence": _score(raw.get("confidence"), 0.0),
                    "risk": _score(raw.get("risk"), 1.0),
                    "mission_alignment": _score(raw.get("mission_alignment"), 0.0),
                    "priority_score": _score(raw.get("priority_score"), 0.0),
                    "safe_to_execute": bool(raw.get("safe_to_execute")),
                    "assist_required": bool(raw.get("assist_required")),
                    "title": _to_text(raw.get("title"), 200),
                }
            )

    add(list((intent_execution or {}).get("execution_candidates") or []), "intent_execution")
    add(list((autonomous_actions or {}).get("execution_candidates") or []), "autonomous_action")
    add(list((value_execution or {}).get("execution_candidates") or []), "value_execution")
    valid = [x for x in out if str(x.get("command") or "").strip()]
    return valid, invalid


def _global_limits_guard(*, user_id: int, organization_id: int, state: dict[str, Any]) -> dict[str, Any]:
    max_exec_per_min = max(1, int((os.getenv("THIRAMAI_MAX_EXECUTIONS_PER_MINUTE") or "30").strip() or 30))
    max_concurrent_runs = max(1, int((os.getenv("THIRAMAI_MAX_CONCURRENT_RUNS_GLOBAL") or "20").strip() or 20))
    now = _now()
    recent = [x for x in list(state.get("recent") or []) if isinstance(x, dict)]
    recent_1m = 0
    for row in recent:
        ts = _parse_iso(row.get("at"))
        if ts is None:
            continue
        if (now - ts).total_seconds() <= 60:
            recent_1m += 1
    if recent_1m >= max_exec_per_min:
        return {"ok": False, "reason": "rate_limit_executions_per_minute", "value": recent_1m, "limit": max_exec_per_min}
    fn = _session_factory_or_none()
    if fn is not None:
        with fn() as session:
            running = session.execute(
                select(ActionExecutionRun.id).where(
                    ActionExecutionRun.user_id == int(user_id),
                    ActionExecutionRun.organization_id == int(organization_id),
                    ActionExecutionRun.status.in_(["planned", "awaiting_confirmation", "running"]),
                ).limit(max_concurrent_runs + 1)
            ).all()
            running_n = len(running)
            if running_n >= max_concurrent_runs:
                return {"ok": False, "reason": "max_concurrent_runs_reached", "value": running_n, "limit": max_concurrent_runs}
    return {"ok": True}


def run_execution_decision_cycle(
    user_id: int,
    organization_id: int,
    *,
    intent_execution: dict[str, Any] | None = None,
    autonomous_actions: dict[str, Any] | None = None,
    value_execution: dict[str, Any] | None = None,
    max_actions_per_cycle: int = 1,
    cooldown_seconds: int = 180,
    failure_backoff_seconds: int = 900,
    execution_trace_id: str | None = None,
) -> dict[str, Any]:
    uid = int(user_id)
    oid = int(organization_id)
    now = _now()
    trace_id = str(execution_trace_id or f"exec-dec-{uid}-{oid}-{uuid4()}")
    t_total0 = time.perf_counter()
    t_exec0 = 0.0
    st = _load_state(user_id=uid, organization_id=oid)
    cd = _parse_iso(st.get("cooldown_until"))
    bo = _parse_iso(st.get("failure_backoff_until"))
    if cd and now < cd:
        return {
            "selected_action": None,
            "rejected_actions": [{"reason": "cooldown_active", "until": cd.isoformat()}],
            "reason_for_selection": "none",
            "reason_for_rejection": "cooldown_active",
            "execution_trace_id": trace_id,
            "timings_ms": {"decision_time": round((time.perf_counter() - t_total0) * 1000.0, 2), "execution_time": 0.0, "total_time": round((time.perf_counter() - t_total0) * 1000.0, 2)},
        }
    if bo and now < bo:
        return {
            "selected_action": None,
            "rejected_actions": [{"reason": "failure_backoff_active", "until": bo.isoformat()}],
            "reason_for_selection": "none",
            "reason_for_rejection": "failure_backoff_active",
            "execution_trace_id": trace_id,
            "timings_ms": {"decision_time": round((time.perf_counter() - t_total0) * 1000.0, 2), "execution_time": 0.0, "total_time": round((time.perf_counter() - t_total0) * 1000.0, 2)},
        }
    limits_guard = _global_limits_guard(user_id=uid, organization_id=oid, state=st)
    if not bool(limits_guard.get("ok")):
        return {
            "selected_action": None,
            "rejected_actions": [{"reason": str(limits_guard.get("reason") or "global_limit_block"), "limit": limits_guard.get("limit"), "value": limits_guard.get("value")}],
            "reason_for_selection": "none",
            "reason_for_rejection": str(limits_guard.get("reason") or "global_limit_block"),
            "reason": "no_safe_action_available",
            "execution_trace_id": trace_id,
            "timings_ms": {"decision_time": round((time.perf_counter() - t_total0) * 1000.0, 2), "execution_time": 0.0, "total_time": round((time.perf_counter() - t_total0) * 1000.0, 2)},
        }

    candidates, invalid_rejections = _normalize_candidates(
        intent_execution=intent_execution,
        autonomous_actions=autonomous_actions,
        value_execution=value_execution,
    )
    rejected: list[dict[str, Any]] = list(invalid_rejections)
    allowed: list[dict[str, Any]] = []
    for c in candidates:
        if not bool(c.get("safe_to_execute")):
            rejected.append({**c, "reason": "unsafe"})
            continue
        if bool(c.get("assist_required")):
            rejected.append({**c, "reason": "assist_required"})
            continue
        c["decision_score"] = _decision_score(c)
        allowed.append(c)
    if not allowed:
        return {
            "selected_action": None,
            "rejected_actions": rejected if rejected else [{"reason": "invalid_schema"}],
            "reason_for_selection": "none",
            "reason_for_rejection": "no_safe_action_available",
            "reason": "no_safe_action_available",
            "execution_trace_id": trace_id,
            "timings_ms": {"decision_time": round((time.perf_counter() - t_total0) * 1000.0, 2), "execution_time": 0.0, "total_time": round((time.perf_counter() - t_total0) * 1000.0, 2)},
        }

    allowed.sort(
        key=lambda x: (
            -float(x.get("decision_score") or 0.0),
            int(SOURCE_PRIORITY.get(str(x.get("source") or ""), 9)),
            float(x.get("risk") or 1.0),
        )
    )
    candidate = allowed[0]

    try:
        trust = float(calculate_prediction_accuracy(uid, limit=200).get("system_trust_score") or 50.0)
    except Exception:
        trust = 50.0
    try:
        perf = monitor_system_performance(user_id=uid, organization_id=oid, hours=24 * 7)
        fail_rate = float(perf.get("failure_rate") or 0.0)
    except Exception:
        fail_rate = 0.0
    try:
        gov = compute_autonomy_decision(
            user_id=uid,
            organization_id=oid,
            domain="automation",
            system_trust_score=trust,
            action_risk_score=float(_score(candidate.get("risk"), 1.0) * 100.0),
            plan_confidence_score=float(_score(candidate.get("confidence"), 0.0)),
            recent_failure_rate=fail_rate,
            repeated_failure_rate=0.0,
            style="balanced",
            active_triggers=[],
        )
    except Exception as exc:
        gov = {"allow_execute": False, "reason": f"governor_exception:{type(exc).__name__}"}
    if not bool(gov.get("allow_execute")):
        rejected.append({**candidate, "reason": "governor_blocked", "governor_reason": _to_text(gov.get("reason"), 220)})
        return {
            "selected_action": None,
            "rejected_actions": rejected,
            "reason_for_selection": "none",
            "reason_for_rejection": "governor_blocked",
            "reason": "no_safe_action_available",
            "execution_trace_id": trace_id,
            "timings_ms": {"decision_time": round((time.perf_counter() - t_total0) * 1000.0, 2), "execution_time": 0.0, "total_time": round((time.perf_counter() - t_total0) * 1000.0, 2)},
        }

    lease = _acquire_execution_lease(user_id=uid, organization_id=oid, lease_seconds=max(30, int(cooldown_seconds)))
    if not bool(lease.get("ok")):
        rejected.append({**candidate, "reason": "lease_active"})
        return {
            "selected_action": None,
            "rejected_actions": rejected,
            "reason_for_selection": "none",
            "reason_for_rejection": str(lease.get("reason") or "lease_active"),
            "reason": "no_safe_action_available",
            "execution_trace_id": trace_id,
            "timings_ms": {"decision_time": round((time.perf_counter() - t_total0) * 1000.0, 2), "execution_time": 0.0, "total_time": round((time.perf_counter() - t_total0) * 1000.0, 2)},
        }
    lease_token = str(lease.get("token") or "")

    max_n = max(1, min(int(max_actions_per_cycle), 1))
    if max_n != 1:
        max_n = 1
    from services.brain_execute import brain_execute
    try:
        t_exec0 = time.perf_counter()
        out = brain_execute(command=str(candidate["command"]), user_id=uid, organization_id=oid)
    except Exception as exc:
        _release_lease(user_id=uid, organization_id=oid, lease_token=lease_token)
        log_structured(
            "execution_decision_error",
            trace_id=trace_id,
            user_id=uid,
            organization_id=oid,
            error_type=type(exc).__name__,
            error=str(exc)[:400],
        )
        rejected.append({**candidate, "reason": "governor_blocked", "governor_reason": f"execution_exception:{type(exc).__name__}"})
        return {
            "selected_action": None,
            "rejected_actions": rejected,
            "reason_for_selection": "none",
            "reason_for_rejection": "no_safe_action_available",
            "reason": "no_safe_action_available",
            "execution_trace_id": trace_id,
            "timings_ms": {"decision_time": round((time.perf_counter() - t_total0) * 1000.0, 2), "execution_time": 0.0, "total_time": round((time.perf_counter() - t_total0) * 1000.0, 2)},
        }
    ok = bool(((out.get("result") if isinstance(out, dict) else {}) or {}).get("ok"))
    cooldown_until = now + timedelta(seconds=max(30, int(cooldown_seconds)))
    backoff_until = None if ok else now + timedelta(seconds=max(60, int(failure_backoff_seconds)))
    _finalize_with_lease(
        user_id=uid,
        organization_id=oid,
        lease_token=lease_token,
        cooldown_until=cooldown_until,
        failure_backoff_until=backoff_until,
        recent_append={
            "source": candidate.get("source"),
            "title": candidate.get("title"),
            "ok": ok,
            "status": _to_text(out.get("status"), 40),
            "at": now.isoformat(),
        },
    )

    for r in allowed[1:]:
        rejected.append({**r, "reason": "lower_score"})
    decision_ms = max(0.0, ((t_exec0 - t_total0) * 1000.0) if t_exec0 > 0 else (time.perf_counter() - t_total0) * 1000.0)
    execution_ms = max(0.0, (time.perf_counter() - t_exec0) * 1000.0) if t_exec0 > 0 else 0.0
    total_ms = max(0.0, (time.perf_counter() - t_total0) * 1000.0)
    log_structured(
        "execution_decision_completed",
        trace_id=trace_id,
        user_id=uid,
        organization_id=oid,
        selected_source=str(candidate.get("source") or ""),
        selected_ok=ok,
        rejected_count=len(rejected),
        decision_time_ms=round(decision_ms, 2),
        execution_time_ms=round(execution_ms, 2),
        total_time_ms=round(total_ms, 2),
    )
    return {
        "selected_action": {
            "source": candidate.get("source"),
            "title": candidate.get("title"),
            "command": candidate.get("command"),
            "ok": ok,
            "status": _to_text(out.get("status"), 40),
            "why_selected": ["highest_score", "passed_safety", "governor_allowed"],
            "score_breakdown": {
                "confidence": _score(candidate.get("confidence"), 0.0),
                "risk": _score(candidate.get("risk"), 1.0),
                "mission_alignment": _score(candidate.get("mission_alignment"), 0.0),
                "priority_score": _score(candidate.get("priority_score"), 0.0),
                "decision_score": _score(candidate.get("decision_score"), 0.0),
            },
        },
        "rejected_actions": rejected,
        "reason_for_selection": "highest_score",
        "reason_for_rejection": "" if not rejected else "other_candidates_rejected",
        "execution_trace_id": trace_id,
        "timings_ms": {"decision_time": round(decision_ms, 2), "execution_time": round(execution_ms, 2), "total_time": round(total_ms, 2)},
    }

