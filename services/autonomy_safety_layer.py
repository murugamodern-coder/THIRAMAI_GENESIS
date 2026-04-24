"""
Production autonomy safety: numeric risk (0–100), approval tiers, budgets, simulation gate,
first-exposure sandbox, global halt, trust-based dampening, and monitoring helpers.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import ExecutionAuditLog

ApprovalTier = Literal["auto", "batch", "explicit"]

# Always auto-gated (read-only / planning); never require batch or explicit.
INTERNAL_SAFETY_ALWAYS_AUTO = frozenset(
    {
        "internal_context_scan",
        "internal_command_analysis",
        "internal_execution_branch",
        "internal_summarize",
    }
)

_REDIS_HALT_KEY = "thiramai:global_autonomy_halt"
_EXPOSURE_KEY = "thiramai:step_kind_seen:{user_id}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _redis():
    try:
        from services.worker_heartbeat import redis_client

        return redis_client()
    except Exception:
        return None


def global_autonomy_halted() -> bool:
    """
    Hard stop for all autonomous / action execution when env or Redis flag is set.
    Use ``THIRAMAI_GLOBAL_AUTONOMY_HALT=1`` or set Redis key ``thiramai:global_autonomy_halt`` to ``1``.
    """
    raw = (os.getenv("THIRAMAI_GLOBAL_AUTONOMY_HALT") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    r = _redis()
    if r is None:
        return False
    try:
        v = r.get(_REDIS_HALT_KEY)
        return str(v or "") == "1"
    except Exception:
        return False


def set_global_autonomy_halt(
    enabled: bool,
    *,
    reason: str = "",
    ttl_sec: int = 0,
) -> dict[str, Any]:
    """
    Set global halt in Redis. Falls back to returning ``persist_env_hint`` if Redis is unavailable
    (operators should set ``THIRAMAI_GLOBAL_AUTONOMY_HALT`` in that case).
    """
    r = _redis()
    if r is None:
        return {
            "ok": True,
            "mode": "env_only",
            "message": f"Set THIRAMAI_GLOBAL_AUTONOMY_HALT={'1' if enabled else '0'}. {reason[:200]}",
        }
    try:
        if enabled:
            r.set(_REDIS_HALT_KEY, "1", ex=ttl_sec if ttl_sec > 0 else None)
        else:
            r.delete(_REDIS_HALT_KEY)
        return {"ok": True, "mode": "redis", "enabled": bool(enabled), "reason": str(reason)[:500]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _base_score_from_risk_string(risk_level: str) -> int:
    lv = str(risk_level or "medium").lower()
    if lv == "low":
        return 22
    if lv == "high":
        return 78
    return 48


def _category_for_step(step_kind: str) -> str:
    sk = str(step_kind or "").lower()
    if "browser" in sk or sk == "plugin_email" or "notify" in sk:
        if "email" in sk or sk == "plugin_email":
            return "communication"
        return "communication" if "browser" in sk else "communication"
    if sk in {"plugin_file"} or "export" in sk or "data" in sk:
        return "data"
    if "plugin_api" in sk or "http" in sk or "webhook" in sk:
        return "data"
    if any(x in sk for x in ("trade", "pay", "invoice", "bank", "money", "order")) or sk == "plugin_payment":
        return "financial"
    if sk.startswith("internal_") or sk in {"internal_summarize"}:
        return "internal"
    if "plugin_" in sk:
        return "communication"
    return "internal"


def _bump_for_category(base: int, category: str) -> int:
    c = (category or "internal").lower()
    if c == "financial":
        return min(100, base + 12)
    if c == "data":
        return min(100, base + 6)
    if c == "communication":
        return min(100, base + 4)
    return max(0, min(100, base))


def classify_action_step(
    step_kind: str,
    risk_level: str,
    *,
    source_command: str = "",
) -> dict[str, Any]:
    """
    Return ``category`` (financial|data|communication|internal), ``risk_score`` 0–100, ``approval_tier``.
    Tiers: risk < 30 auto, 30–70 batch, > 70 explicit (aligned with product policy).
    """
    base = _base_score_from_risk_string(risk_level)
    cat = _category_for_step(step_kind)
    sk = str(step_kind or "")
    sc = (source_command or "")[:2000]
    t = f"{sk} {sc}".lower()

    if any(k in t for k in ("$", "usd", "payment", "card charge", "bank transfer", "execute trade")):
        cat = "financial"
        base = max(base, 55)
    if "delete" in t and ("database" in t or "all records" in t or "wipe" in t):
        base = max(base, 72)
    if "webhook" in t or "post" in t and "api" in t:
        base = max(base, 58)

    score = _bump_for_category(base, cat)

    if score < 30:
        tier: ApprovalTier = "auto"
    elif score <= 70:
        tier = "batch"
    else:
        tier = "explicit"

    return {
        "category": cat,
        "risk_score": int(max(0, min(100, score))),
        "approval_tier": tier,
    }


def approval_tier_from_score(score: int) -> ApprovalTier:
    s = int(max(0, min(100, score)))
    if s < 30:
        return "auto"
    if s <= 70:
        return "batch"
    return "explicit"


def apply_trust_damping(risk_score: int, trust_0_100: float) -> int:
    """Lower trust nudges score upward (more confirmation), capped at 100."""
    t = max(0.0, min(100.0, float(trust_0_100)))
    if t >= 55.0:
        return int(risk_score)
    bump = int((55.0 - t) * 0.45)
    return int(max(0, min(100, risk_score + bump)))


def get_system_trust_score(user_id: int) -> float:
    try:
        from services.feedback_engine import calculate_prediction_accuracy

        return float(calculate_prediction_accuracy(int(user_id), limit=220).get("system_trust_score") or 50.0)
    except Exception:
        return 50.0


def suggest_autonomy_level_for_trust(trust_0_100: float) -> str:
    """
    Gradual unlock: start conservative; promote when trust is healthy.
    """
    t = max(0.0, min(100.0, float(trust_0_100)))
    if t < 50.0:
        return "assist"
    if t < 70.0:
        return "semi_auto"
    return "full_auto"


def _daily_risk_cap() -> int:
    try:
        return max(50, int((os.getenv("THIRAMAI_DAILY_RISK_BUDGET") or "2000").strip() or "2000"))
    except ValueError:
        return 2000


def _per_action_risk_cap() -> int:
    try:
        return max(1, int((os.getenv("THIRAMAI_PER_ACTION_RISK_CAP") or "95").strip() or "95"))
    except ValueError:
        return 95


def _sum_risk_consumed_24h(user_id: int) -> int:
    try:
        fn = get_session_factory()
    except Exception:
        return 0
    if fn is None:
        return 0
    since = _now() - timedelta(hours=24)
    with fn() as session:
        rows = (
            session.execute(
                select(ExecutionAuditLog).where(
                    ExecutionAuditLog.user_id == int(user_id),
                    ExecutionAuditLog.action_type == "action_layer_step",
                    ExecutionAuditLog.created_at >= since,
                )
            )
            .scalars()
            .all()
        )
    total = 0.0
    for rec in rows:
        pj = rec.payload_json
        if not isinstance(pj, dict):
            continue
        try:
            total += float(pj.get("safety_risk_score") or 0)
        except (TypeError, ValueError):
            continue
    return int(total)


def check_risk_budget(user_id: int, proposed_step_risk: int) -> dict[str, Any]:
    cap = _daily_risk_cap()
    pcap = _per_action_risk_cap()
    if proposed_step_risk > pcap:
        return {
            "ok": True,
            "allowed": False,
            "reason": f"Per-action risk cap exceeded ({proposed_step_risk} > {pcap})",
        }
    used = _sum_risk_consumed_24h(int(user_id))
    if used + int(proposed_step_risk) > cap:
        return {
            "ok": True,
            "allowed": False,
            "reason": f"Daily risk budget exceeded ({used}+{proposed_step_risk} > {cap})",
        }
    return {"ok": True, "allowed": True, "used_24h": used, "cap": cap}


def sim_success_threshold() -> float:
    try:
        return max(0.1, min(0.99, float((os.getenv("THIRAMAI_SIM_MIN_SUCCESS") or "0.52").strip() or 0.52)))
    except ValueError:
        return 0.52


def pre_execution_simulation_gate(
    user_id: int,
    *,
    source_command: str,
    max_step_risk: int,
) -> dict[str, Any]:
    """
    For high max risk, require simulation first; block if best-path success probability is below threshold.
    """
    if max_step_risk < 70:
        return {"ok": True, "proceed": True, "skipped": True, "reason": "below_high_risk_sim_threshold"}
    try:
        from services.simulation_engine import choose_best_simulated_path

        ctx: dict[str, Any] = {"action_summary": (source_command or "")[:2000], "max_step_risk": max_step_risk}
        out = choose_best_simulated_path(int(user_id), ctx)
        rec = (out.get("simulation") or {}).get("recommended_path") or {}
        p = float(rec.get("success_probability") or 0.0)
        thr = sim_success_threshold()
        if p < thr:
            return {
                "ok": True,
                "proceed": False,
                "reason": "simulation_insufficient",
                "success_probability": p,
                "threshold": thr,
                "path": rec,
            }
        return {
            "ok": True,
            "proceed": True,
            "success_probability": p,
            "threshold": thr,
            "path": rec,
        }
    except Exception as exc:
        return {
            "ok": False,
            "proceed": False,
            "error": str(exc),
            "reason": "simulation_error",
        }


def sandbox_first_steps_enabled() -> bool:
    return (os.getenv("THIRAMAI_SAFETY_SANDBOX_FIRST_STEPS") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def is_first_exposure(user_id: int, step_kind: str) -> bool:
    r = _redis()
    if r is None:
        return False
    key = _EXPOSURE_KEY.format(user_id=int(user_id))
    m = f"{int(user_id)}:{str(step_kind)[:120]}"
    try:
        return not r.sismember(key, m)
    except Exception:
        return False


def mark_step_kind_exposed(user_id: int, step_kind: str) -> None:
    r = _redis()
    if r is None:
        return
    key = _EXPOSURE_KEY.format(user_id=int(user_id))
    m = f"{int(user_id)}:{str(step_kind)[:120]}"
    try:
        r.sadd(key, m)
        r.expire(key, 86400 * 90)
    except Exception:
        pass


def safety_monitoring_summary(user_id: int, *, hours: int = 24) -> dict[str, Any]:
    try:
        fn = get_session_factory()
    except Exception:
        return {"ok": False, "items": []}
    if fn is None:
        return {"ok": False, "items": []}
    since = _now() - timedelta(hours=max(1, int(hours)))
    with fn() as session:
        rows = (
            session.execute(
                select(ExecutionAuditLog)
                .where(
                    ExecutionAuditLog.user_id == int(user_id),
                    ExecutionAuditLog.source == "action_engine",
                    ExecutionAuditLog.created_at >= since,
                )
                .order_by(ExecutionAuditLog.created_at.desc())
            )
            .scalars()
            .all()[:200]
        )
    fails = 0
    success = 0
    retries = 0
    for r in rows:
        st = str(r.status or "").lower()
        if st in ("failed", "error", "blocked"):
            fails += 1
        elif st in ("success", "ok", "succeeded", "complete"):
            success += 1
        pj = r.payload_json or {}
        retries += int(pj.get("retries") or 0) if isinstance(pj, dict) else 0
    total = max(1, fails + success)
    fr = fails / float(total)
    ab = fr > 0.35 and (fails + success) >= 8
    return {
        "ok": True,
        "window_hours": hours,
        "failures": fails,
        "successes": success,
        "retry_count_hint": retries,
        "failure_rate": round(fr, 3),
        "anomaly_suspected": ab,
    }
