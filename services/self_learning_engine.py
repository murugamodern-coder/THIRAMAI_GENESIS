"""
Self-learning engine: daily knowledge/skill evolution loop (learning only).

Constraints:
- No code self-modification
- No unsafe execution
- Produces learn/simulate/improve tasks only
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


def _pick_top_topics(realtime_research: dict[str, Any], *, max_n: int = 2) -> list[dict[str, Any]]:
    updates = [u for u in list((realtime_research or {}).get("daily_updates") or []) if isinstance(u, dict)]
    ranked = sorted(
        updates,
        key=lambda x: (
            _score(x.get("opportunity_score"), 0.0),
            _score(x.get("mission_alignment"), 0.0),
            _score(x.get("importance"), 0.0),
        ),
        reverse=True,
    )
    return ranked[: max(1, min(max_n, 4))]


def run_self_learning_cycle(
    user_id: int,
    organization_id: int,
    *,
    realtime_research: dict[str, Any] | None = None,
    value_generation: dict[str, Any] | None = None,
    result_execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    uid = int(user_id)
    oid = int(organization_id)
    identity = load_master_identity_context()
    rr = realtime_research if isinstance(realtime_research, dict) else {}
    vg = value_generation if isinstance(value_generation, dict) else {}
    rx = result_execution if isinstance(result_execution, dict) else {}

    top_topics = _pick_top_topics(rr, max_n=2)
    new_knowledge_acquired: list[dict[str, Any]] = []
    for t in top_topics:
        title = _to_text(t.get("title"), 220)
        domain = _to_text(t.get("domain") or "general", 60)
        align = score_long_term_alignment(title, identity)
        new_knowledge_acquired.append(
            {
                "topic": title,
                "domain": domain,
                "deep_summary": (
                    f"{domain.upper()} signal: {title}. "
                    "Likely strategic effect: capability/cost/timing shift; validate through a controlled internal brief."
                )[:420],
                "use_case_ideas": [
                    "Run a short internal scenario simulation on impact to current roadmap.",
                    "Create one pilot hypothesis tied to measurable business or capability gains.",
                ],
                "strategic_relevance": round(max(0.0, min(1.0, align)), 4),
                "source": _to_text(t.get("source"), 120),
            }
        )

    failures = [f for f in list(rx.get("failures") or []) if isinstance(f, dict)]
    executed = [e for e in list(rx.get("executed_actions") or []) if isinstance(e, dict)]
    failed_exec = [e for e in executed if not bool(e.get("success"))]
    activated = [a for a in list(vg.get("activated_opportunities") or []) if isinstance(a, dict)]
    missed = [a for a in activated if bool(a.get("assist_required")) or not bool(a.get("safe_to_execute"))]

    skills_improved: list[dict[str, Any]] = []
    if failures or failed_exec:
        skills_improved.append(
            {
                "skill": "failure_pattern_handling",
                "improvement": "Strengthen preflight assumptions and fallback design for recurring execution exceptions.",
                "evidence_count": len(failures) + len(failed_exec),
            }
        )
    if missed:
        skills_improved.append(
            {
                "skill": "opportunity_translation",
                "improvement": "Improve conversion of high-value but assist-required opportunities into lower-risk staged experiments.",
                "evidence_count": len(missed),
            }
        )
    if not skills_improved:
        skills_improved.append(
            {
                "skill": "decision_quality_stability",
                "improvement": "Maintain current strategy profile while expanding domain-specific signal interpretation.",
                "evidence_count": 0,
            }
        )

    knowledge_gaps_detected: list[dict[str, Any]] = []
    if failures:
        knowledge_gaps_detected.append(
            {
                "gap": "runtime_error_diagnostics_depth",
                "why": "Execution failures indicate missing diagnostic heuristics for robust retries.",
            }
        )
    if missed:
        knowledge_gaps_detected.append(
            {
                "gap": "risk_decomposition_for_high_value_opportunities",
                "why": "High-value opportunities remain assist-only and need safer decomposition templates.",
            }
        )
    if not knowledge_gaps_detected:
        knowledge_gaps_detected.append(
            {
                "gap": "cross_domain_signal_synthesis",
                "why": "Need stronger cross-linking between realtime signals and value hypotheses.",
            }
        )

    self_improvement_tasks = {
        "learning_tasks": [
            {
                "title": "Create daily mission-linked knowledge brief",
                "mode": "learn_only",
                "safe_to_execute": True,
                "assist_required": False,
            },
            {
                "title": "Catalog 2 reusable opportunity patterns from today signals",
                "mode": "learn_only",
                "safe_to_execute": True,
                "assist_required": False,
            },
        ],
        "simulation_tasks": [
            {
                "title": "Simulate low-risk path for one assist-required opportunity",
                "mode": "simulate_only",
                "safe_to_execute": True,
                "assist_required": False,
            }
        ],
        "improvement_actions": [
            {
                "title": "Add one guardrail recommendation for top failure pattern",
                "mode": "improvement_recommendation_only",
                "safe_to_execute": True,
                "assist_required": False,
            }
        ],
    }

    # Memory updates (learning artifacts only).
    for row in new_knowledge_acquired[:4]:
        record_identity_memory(
            user_id=uid,
            organization_id=oid,
            memory_type="learned_concepts",
            item=row,
        )
    for row in skills_improved[:4]:
        record_identity_memory(
            user_id=uid,
            organization_id=oid,
            memory_type="improved_strategies",
            item=row,
        )
    for row in knowledge_gaps_detected[:4]:
        record_identity_memory(
            user_id=uid,
            organization_id=oid,
            memory_type="new_capabilities",
            item=row,
        )

    return {
        "new_knowledge_acquired": new_knowledge_acquired,
        "skills_improved": skills_improved,
        "knowledge_gaps_detected": knowledge_gaps_detected,
        "self_improvement_tasks": self_improvement_tasks,
    }

