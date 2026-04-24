"""
Value generation engine: produce actionable value signals every cycle.
"""

from __future__ import annotations

from typing import Any

from services.domain_execution_intelligence import load_domain_execution_context
from services.identity_context_loader import (
    compute_identity_influence,
    load_master_identity_context,
    score_long_term_alignment,
)
from services.p2_intelligence import build_pattern_intelligence, decision_memory_context


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _risk_bucket(v: float) -> str:
    if v >= 0.70:
        return "high"
    if v >= 0.40:
        return "medium"
    return "low"


def _candidate(
    *,
    category: str,
    title: str,
    why: str,
    mission_alignment: float,
    roi_potential: float,
    risk: float,
    execution_feasibility: float,
    execution_steps: list[str],
) -> dict[str, Any]:
    mission_alignment = max(0.0, min(1.0, mission_alignment))
    roi_potential = max(0.0, min(1.0, roi_potential))
    risk = max(0.0, min(1.0, risk))
    execution_feasibility = max(0.0, min(1.0, execution_feasibility))
    score = (0.35 * mission_alignment) + (0.35 * roi_potential) + (0.20 * execution_feasibility) - (0.20 * risk)
    safe = risk < 0.70
    return {
        "category": category,
        "title": title,
        "why": why,
        "mission_alignment": round(mission_alignment, 4),
        "roi_potential": round(roi_potential, 4),
        "risk": round(risk, 4),
        "risk_level": _risk_bucket(risk),
        "execution_feasibility": round(execution_feasibility, 4),
        "execution_steps": [str(x)[:220] for x in list(execution_steps or [])][:6],
        "safe_to_execute": bool(safe),
        "assist_required": bool(not safe),
        "priority_score": round(max(0.0, min(1.0, score)), 4),
    }


def _default_non_empty_payload(identity_ctx: dict[str, Any]) -> dict[str, Any]:
    mission = str(identity_ctx.get("mission") or "Deliver mission-aligned value.")
    opp = _candidate(
        category="new_opportunities",
        title="Revenue uplift from workflow bottleneck elimination",
        why="Execution data is sparse; use a conservative opportunity baseline with measurable weekly ROI.",
        mission_alignment=0.68,
        roi_potential=0.64,
        risk=0.32,
        execution_feasibility=0.72,
        execution_steps=[
            "Identify one repeatable revenue bottleneck from recent operations.",
            "Run a one-week constrained pilot and measure uplift.",
        ],
    )
    imp = _candidate(
        category="improvements",
        title="Reduce repeat failure loops with preflight hardening",
        why="Failure-memory signal indicates value leakage in retries and rework.",
        mission_alignment=0.71,
        roi_potential=0.52,
        risk=0.22,
        execution_feasibility=0.79,
        execution_steps=[
            "Map top recurring error classes.",
            "Add one guardrail per error class before execution dispatch.",
        ],
    )
    ins = _candidate(
        category="research_insights",
        title="Track strategic capability drift in automation decision quality",
        why=mission,
        mission_alignment=0.74,
        roi_potential=0.49,
        risk=0.18,
        execution_feasibility=0.68,
        execution_steps=[
            "Log decision-quality trend weekly.",
            "Correlate quality drift with external triggers and system trust.",
        ],
    )
    move = _candidate(
        category="strategic_moves",
        title="Stage-gated capital allocation for high-confidence initiatives",
        why="Concentrating capital on high-confidence initiatives compounds execution speed.",
        mission_alignment=0.78,
        roi_potential=0.63,
        risk=0.41,
        execution_feasibility=0.66,
        execution_steps=[
            "Allocate a fixed share to highest-priority validated initiatives.",
            "Require milestone evidence before increasing allocation.",
        ],
    )
    priority = sorted([opp, imp, ins, move], key=lambda x: float(x.get("priority_score") or 0.0), reverse=True)
    return {
        "new_opportunities": [opp],
        "improvements": [imp],
        "research_insights": [ins],
        "strategic_moves": [move],
        "priority_ranking": priority,
        "activated_opportunities": [],
    }


def _from_realtime_activated(
    realtime_output: dict[str, Any],
    *,
    long_align: float,
    identity_influence: float,
) -> list[dict[str, Any]]:
    rows = [x for x in list((realtime_output or {}).get("activated_opportunities") or []) if isinstance(x, dict)]
    out: list[dict[str, Any]] = []
    for r in rows[:8]:
        mission_alignment = max(
            0.0,
            min(1.0, float(r.get("mission_alignment") or long_align)),
        )
        roi = max(0.0, min(1.0, float(r.get("roi_potential") or r.get("expected_value") or 0.5)))
        risk = max(0.0, min(1.0, float(r.get("risk") or 0.4)))
        urgency = max(0.0, min(1.0, float(r.get("urgency") or 0.5)))
        actionability = max(0.0, min(1.0, float(r.get("actionability_score") or 0.5)))
        base = _candidate(
            category="new_opportunities",
            title=str(r.get("title") or "Activated realtime opportunity")[:220],
            why=str(r.get("why_now") or "Derived from real-time research signal.")[:320],
            mission_alignment=mission_alignment,
            roi_potential=roi,
            risk=risk,
            execution_feasibility=max(0.3, min(1.0, (0.50 * actionability) + (0.35 * urgency) + (0.15 * identity_influence))),
            execution_steps=[str(x)[:220] for x in list(r.get("execution_path") or [])][:6],
        )
        boost = (0.18 * urgency) + (0.14 * roi) + (0.16 * mission_alignment)
        base["priority_score"] = round(max(0.0, min(1.0, float(base.get("priority_score") or 0.0) + boost)), 4)
        base["source"] = str(r.get("source") or "realtime_research")
        base["timestamp"] = str(r.get("timestamp") or "")
        base["confidence"] = round(max(0.0, min(1.0, float(r.get("confidence") or 0.5))), 4)
        base["opportunity_score"] = round(max(0.0, min(1.0, float(r.get("opportunity_score") or 0.0))), 4)
        base["actionability_score"] = round(actionability, 4)
        base["urgency"] = round(urgency, 4)
        # Safety hook for result execution engine.
        if isinstance(r.get("safe_to_execute"), bool):
            base["safe_to_execute"] = bool(r.get("safe_to_execute"))
        if isinstance(r.get("assist_required"), bool):
            base["assist_required"] = bool(r.get("assist_required"))
        out.append(base)
    return out


def run_value_generation_cycle(
    user_id: int,
    organization_id: int,
    *,
    command_hint: str = "",
    execution_memory: dict[str, Any] | None = None,
    domain_context: dict[str, Any] | None = None,
    identity_context: dict[str, Any] | None = None,
    failure_playbook: dict[str, Any] | None = None,
    pattern_intelligence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    uid = int(user_id)
    oid = int(organization_id)
    identity_ctx = identity_context if isinstance(identity_context, dict) else load_master_identity_context()
    domain_ctx = domain_context if isinstance(domain_context, dict) else load_domain_execution_context(
        user_id=uid,
        organization_id=oid,
        command=str(command_hint or "value_generation_cycle"),
        context={"source": "value_generation_engine", "agent_identity": identity_ctx},
    )
    decision_mem = execution_memory if isinstance(execution_memory, dict) else decision_memory_context(
        user_id=uid,
        organization_id=oid,
    )
    p_intel = pattern_intelligence if isinstance(pattern_intelligence, dict) else build_pattern_intelligence(
        user_id=uid,
        organization_id=oid,
    )
    playbook = failure_playbook if isinstance(failure_playbook, dict) else dict(p_intel.get("failure_playbook") or {})

    success_rate = _to_float(decision_mem.get("decision_success_rate"), 0.5)
    fail_clusters = list(playbook.get("clusters") or [])
    cluster_count = len([x for x in fail_clusters if isinstance(x, dict)])
    domain_name = str(domain_ctx.get("domain") or "general")
    mission = str(identity_ctx.get("mission") or "")
    long_align = score_long_term_alignment(str(command_hint or mission), identity_ctx)
    identity_influence = compute_identity_influence(
        mission_alignment_score=max(0.0, min(1.0, success_rate)),
        long_term_alignment=long_align,
        identity_ctx=identity_ctx,
    )
    suppression_clusters = list(p_intel.get("suppression_clusters") or [])
    reusable = list(p_intel.get("reusable_strategies") or [])
    realtime_output = (
        domain_ctx.get("realtime_research")
        if isinstance(domain_ctx, dict) and isinstance(domain_ctx.get("realtime_research"), dict)
        else {}
    )

    opportunity = _candidate(
        category="new_opportunities",
        title=f"Monetize high-signal {domain_name} demand pockets",
        why="Pattern intelligence identifies repeatable opportunities where execution confidence is strongest.",
        mission_alignment=max(0.45, (0.55 * long_align) + (0.30 * identity_influence)),
        roi_potential=max(0.40, min(0.92, (0.50 + (0.25 * success_rate) + (0.02 * len(reusable))))),
        risk=max(0.15, min(0.72, 0.46 - (0.12 * success_rate))),
        execution_feasibility=max(0.45, min(0.9, 0.62 + (0.10 * len(reusable)) - (0.03 * cluster_count))),
        execution_steps=[
            "Select one high-confidence segment from recent successful patterns.",
            "Launch a constrained offer and track weekly conversion + margin.",
            "Scale only if ROI and governance thresholds are met.",
        ],
    )
    improvement = _candidate(
        category="improvements",
        title="Failure-cluster suppression and process hardening",
        why="Reducing repeated failure classes converts hidden execution waste into immediate value.",
        mission_alignment=max(0.50, (0.60 * long_align) + 0.22),
        roi_potential=max(0.35, min(0.85, 0.44 + (0.03 * cluster_count))),
        risk=max(0.08, min(0.50, 0.24 + (0.01 * max(0, cluster_count - 3)))),
        execution_feasibility=max(0.52, min(0.95, 0.66 + (0.02 * len(suppression_clusters)))),
        execution_steps=[
            "Take top 3 recurring failure clusters from playbook.",
            "Apply preflight checks and fallback paths for each cluster.",
            "Track retry-rate reduction and throughput gain.",
        ],
    )
    research = _candidate(
        category="research_insights",
        title="Strategic signal watchlist for future capability advantage",
        why="Early weak-signal detection compounds long-term strategic optionality.",
        mission_alignment=max(0.55, (0.70 * long_align) + 0.10),
        roi_potential=max(0.28, min(0.78, 0.36 + (0.18 * identity_influence))),
        risk=max(0.12, min(0.66, 0.34 - (0.08 * success_rate))),
        execution_feasibility=max(0.42, min(0.88, 0.58 + (0.06 * success_rate))),
        execution_steps=[
            "Track two external strategic signals tied to mission goals.",
            "Run one low-cost validation experiment per signal.",
            "Promote only validated signals into strategic move candidates.",
        ],
    )
    strategic = _candidate(
        category="strategic_moves",
        title="Reallocate capacity toward highest mission-aligned initiatives",
        why="Mission-weighted allocation improves both near-term value and long-term positioning.",
        mission_alignment=max(0.60, (0.75 * long_align) + (0.10 * identity_influence)),
        roi_potential=max(0.33, min(0.88, 0.47 + (0.20 * success_rate))),
        risk=max(0.20, min(0.76, 0.42 - (0.10 * success_rate))),
        execution_feasibility=max(0.40, min(0.86, 0.55 + (0.08 * identity_influence))),
        execution_steps=[
            "Rank current initiatives by mission alignment, ROI, and feasibility.",
            "Shift incremental resources to top-ranked initiative.",
            "Review impact weekly; revert if risk exceeds threshold.",
        ],
    )

    base = {
        "new_opportunities": [opportunity],
        "improvements": [improvement],
        "research_insights": [research],
        "strategic_moves": [strategic],
    }
    activated = _from_realtime_activated(
        realtime_output if isinstance(realtime_output, dict) else {},
        long_align=long_align,
        identity_influence=identity_influence,
    )
    if activated:
        base["new_opportunities"].extend(activated[:5])
    all_rows = list(base["new_opportunities"]) + [improvement, research, strategic]
    base["priority_ranking"] = sorted(all_rows, key=lambda x: float(x.get("priority_score") or 0.0), reverse=True)
    base["activated_opportunities"] = activated[:8]
    base["inputs_snapshot"] = {
        "domain": domain_name,
        "decision_success_rate": round(success_rate, 4),
        "failure_clusters": cluster_count,
        "identity_influence": round(identity_influence, 4),
        "long_term_alignment": round(long_align, 4),
    }

    if not base["new_opportunities"] or not base["improvements"] or not base["research_insights"]:
        return _default_non_empty_payload(identity_ctx)
    return base

