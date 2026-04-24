"""
Continuous intelligence engine: ongoing thinking artifacts without direct execution.
"""

from __future__ import annotations

from typing import Any

from services.agent_identity_continuity_engine import record_identity_memory
from services.identity_context_loader import load_master_identity_context, score_long_term_alignment


def _to_text(v: Any, n: int = 320) -> str:
    return str(v or "").strip().replace("\n", " ")[:n]


def _score(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except Exception:
        x = float(default)
    return max(0.0, min(1.0, x))


def run_continuous_thinking(
    user_id: int,
    organization_id: int,
    *,
    realtime_research: dict[str, Any] | None = None,
    value_generation: dict[str, Any] | None = None,
    result_execution: dict[str, Any] | None = None,
    identity_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    uid = int(user_id)
    oid = int(organization_id)
    rr = realtime_research if isinstance(realtime_research, dict) else {}
    vg = value_generation if isinstance(value_generation, dict) else {}
    rx = result_execution if isinstance(result_execution, dict) else {}
    identity = identity_context if isinstance(identity_context, dict) else load_master_identity_context()

    updates = [u for u in list(rr.get("daily_updates") or []) if isinstance(u, dict)]
    activated = [a for a in list(vg.get("activated_opportunities") or []) if isinstance(a, dict)]
    results = [r for r in list(rx.get("results") or []) if isinstance(r, dict)]
    failures = [f for f in list(rx.get("failures") or []) if isinstance(f, dict)]

    # Thinking type 1: connect unrelated signals.
    new_insights: list[dict[str, Any]] = []
    if len(updates) >= 2:
        a, b = updates[0], updates[1]
        insight_txt = (
            f"Signal-link insight: '{_to_text(a.get('title'), 120)}' + "
            f"'{_to_text(b.get('title'), 120)}' may form a compounded opportunity if sequenced in one roadmap."
        )
        new_insights.append(
            {
                "insight": insight_txt,
                "confidence": round(max(0.35, min(0.92, (0.45 * _score(a.get('confidence'), 0.5)) + (0.45 * _score(b.get('confidence'), 0.5)))), 4),
                "domain": "cross_domain",
            }
        )
    else:
        new_insights.append(
            {
                "insight": "Insufficient multi-signal context today; prioritize widening external signal coverage for stronger cross-domain synthesis.",
                "confidence": 0.52,
                "domain": "intelligence_coverage",
            }
        )

    # Thinking type 2 + 3: hidden opportunities and predicted next moves.
    strategic_thoughts: list[dict[str, Any]] = []
    top_activated = sorted(
        activated,
        key=lambda x: (
            _score(x.get("opportunity_score"), 0.0),
            _score(x.get("actionability_score"), 0.0),
            _score(x.get("mission_alignment"), 0.0),
        ),
        reverse=True,
    )[:3]
    for a in top_activated:
        title = _to_text(a.get("title"), 180)
        ma = _score(a.get("mission_alignment"), 0.0)
        strategic_thoughts.append(
            {
                "thought": f"Predictive move: stage a low-risk pilot around '{title}' before competitors price in the shift.",
                "mission_alignment": round(ma, 4),
                "next_move_window": "24-72h",
            }
        )
    if not strategic_thoughts:
        strategic_thoughts.append(
            {
                "thought": "Pipeline health is stable; next strategic move is increasing signal-to-opportunity conversion rate.",
                "mission_alignment": round(score_long_term_alignment("increase conversion rate", identity), 4),
                "next_move_window": "next_cycle",
            }
        )

    # Thinking type 4: future scenario simulation.
    detected_opportunities: list[dict[str, Any]] = []
    for a in top_activated:
        opp = {
            "title": _to_text(a.get("title"), 200),
            "scenario_if_acted": "Early pilot creates compounding informational and execution advantage.",
            "scenario_if_ignored": "Opportunity decays as market diffusion reduces asymmetry.",
            "opportunity_score": round(_score(a.get("opportunity_score"), 0.0), 4),
            "confidence": round(_score(a.get("confidence"), 0.5), 4),
            "safe_to_execute": bool(a.get("safe_to_execute")),
            "assist_required": bool(a.get("assist_required")),
        }
        detected_opportunities.append(opp)

    if not detected_opportunities and updates:
        u = updates[0]
        detected_opportunities.append(
            {
                "title": _to_text(u.get("title"), 200),
                "scenario_if_acted": "Capture first-order learning rapidly.",
                "scenario_if_ignored": "Lower strategic readiness for related domain shifts.",
                "opportunity_score": round(_score(u.get("opportunity_score"), 0.5), 4),
                "confidence": round(_score(u.get("confidence"), 0.5), 4),
                "safe_to_execute": True,
                "assist_required": False,
            }
        )

    # Action trigger candidates (still no direct execution).
    self_generated_actions: list[dict[str, Any]] = []
    for d in detected_opportunities[:6]:
        if (
            _score(d.get("opportunity_score"), 0.0) >= 0.72
            and _score(d.get("confidence"), 0.0) >= 0.65
            and bool(d.get("safe_to_execute"))
            and not bool(d.get("assist_required"))
        ):
            self_generated_actions.append(
                {
                    "type": "auto_action_candidate",
                    "title": f"Candidate: {_to_text(d.get('title'), 180)}",
                    "reason": "High opportunity/high confidence/safe candidate. Must route via brain_execute + governor.",
                    "route": "brain_execute",
                    "safe_to_execute": True,
                    "assist_required": False,
                    "direct_execution": False,
                }
            )

    # Add penalty thought when recent failures are visible.
    if failures:
        self_generated_actions.append(
            {
                "type": "stability_candidate",
                "title": "Candidate: stabilize repeated failure points before scaling opportunity actions",
                "reason": f"{len(failures)} failures detected in recent cycle.",
                "route": "brain_execute",
                "safe_to_execute": True,
                "assist_required": False,
                "direct_execution": False,
            }
        )

    # Memory writes (thoughts/insights/decisions only).
    for row in new_insights[:4]:
        record_identity_memory(user_id=uid, organization_id=oid, memory_type="thoughts", item=row)
    for row in strategic_thoughts[:4]:
        record_identity_memory(user_id=uid, organization_id=oid, memory_type="insights", item=row)
    for row in self_generated_actions[:4]:
        record_identity_memory(user_id=uid, organization_id=oid, memory_type="decisions", item=row)

    return {
        "new_insights": new_insights,
        "strategic_thoughts": strategic_thoughts,
        "detected_opportunities": detected_opportunities,
        "self_generated_actions": self_generated_actions,
    }

