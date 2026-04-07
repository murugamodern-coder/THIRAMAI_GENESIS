"""
Personal AI Director — orchestrates life memory, calendar, proactive, dashboard, decision, context.

Used by ``GET /personal/today`` to add **additive** fields without breaking legacy clients.
"""

from __future__ import annotations

from typing import Any

from core.calendar_engine import calendar_summary
from core.personal_life_context import build_life_context
from core.life_dashboard import build_life_dashboard
from core.life_memory import detect_patterns_sync, get_user_profile_sync
from core.personal_decision_engine import decision_bundle
from core.proactive_engine import compute_proactive_alerts


def build_personal_director_bundle_sync(
    payload: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    engagement_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Returns keys to merge onto the today payload: ``life_context``, ``priority_tasks``,
    ``proactive_alerts``, ``life_score``, plus ``guidance_enrichment`` for the guidance dict.
    """
    uid = int(payload.get("user_id") or 0)
    oid = int(payload.get("organization_id") or 0)
    authed = bool(payload.get("authenticated"))

    if not authed or uid <= 0:
        return _anonymous_bundle()

    cal = calendar_summary(snapshot)
    life_ctx = build_life_context(snapshot, cal, engagement_extra=engagement_extra)
    proactive = compute_proactive_alerts(snapshot, engagement_extra=engagement_extra)
    life_score = build_life_dashboard(payload, user_id=uid, organization_id=oid)
    decisions = decision_bundle(snapshot)
    profile = get_user_profile_sync(uid, oid)
    patterns = detect_patterns_sync(uid, oid)

    memory_suggestions: list[str] = []
    if patterns.get("summary"):
        memory_suggestions.append(str(patterns["summary"]))
    if profile.get("past_decisions"):
        memory_suggestions.append("Recent decisions logged — use them to avoid re-debating the same choices.")
    if len(profile.get("long_term_goals") or []) >= 4:
        memory_suggestions.append("Several active goals — sequence one primary for this week.")

    enrichment: dict[str, Any] = {
        "memory_based_suggestions": memory_suggestions[:6],
        "director_mode": life_ctx.get("mode"),
        "next_best_move": decisions.get("next_best_move"),
        "balance_tip": (decisions.get("balance") or {}).get("tip"),
        "life_memory_profile_compact": {
            "open_goals_n": int((profile.get("stats") or {}).get("open_missions") or 0),
            "habit_checkins_14d": int((profile.get("habits_history") or {}).get("check_ins_last_14d") or 0),
        },
    }

    return {
        "life_context": life_ctx,
        "priority_tasks": decisions.get("priority_tasks") or [],
        "proactive_alerts": proactive,
        "life_score": life_score,
        "guidance_enrichment": enrichment,
    }


def _anonymous_bundle() -> dict[str, Any]:
    return {
        "life_context": {
            "mode": "reflect",
            "mode_reason": "Sign in to personalize your director.",
            "calendar": {"workload_band": "clear", "overload": False, "free_slots_preview": 0},
            "signals": {"open_tasks": 0, "upcoming_reminders": 0, "daily_score": 0, "actions_today": 0},
        },
        "priority_tasks": [],
        "proactive_alerts": [],
        "life_score": {
            "health_score": None,
            "health_source": "anonymous",
            "productivity_score": 0,
            "financial_signal": "unknown",
            "workload_level": "unknown",
        },
        "guidance_enrichment": {
            "memory_based_suggestions": [],
            "director_mode": "reflect",
            "next_best_move": None,
            "balance_tip": None,
            "life_memory_profile_compact": {},
        },
    }


def apply_director_enrichment_to_guidance(guidance: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
    """Non-destructive merge of director fields into guidance."""
    out = dict(guidance)
    for k, v in enrichment.items():
        if v is None and k not in out:
            continue
        out[k] = v
    return out
