"""
Multi-agent collaboration layer:
- role agents (researcher / executor / strategist / negotiator)
- shared memory + message passing
- coordinator orchestration + final synthesis
"""

from __future__ import annotations

import re
from typing import Any


def _now_label() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _is_complex_goal(goal: str) -> bool:
    g = str(goal or "")
    if len(g) > 220:
        return True
    if len(re.split(r"\b(?:and|then|after|next|;|,)\b", g, flags=re.I)) >= 4:
        return True
    cues = ("strategy", "plan", "workflow", "pipeline", "negotiate", "execute", "research")
    return sum(1 for c in cues if c in g.lower()) >= 3


def _decompose_goal(goal: str) -> list[str]:
    chunks = re.split(r"\b(?:and then|then|after that|next|;|\.)\b", str(goal or ""), flags=re.I)
    out = [c.strip(" -,:") for c in chunks if c.strip()]
    return [x[:280] for x in out][:10] or [str(goal or "").strip()[:280]]


def _send_message(shared_memory: dict[str, Any], *, from_agent: str, to_agent: str, content: str) -> None:
    msgs = list(shared_memory.get("messages") or [])
    msgs.append(
        {
            "at": _now_label(),
            "from": str(from_agent)[:64],
            "to": str(to_agent)[:64],
            "content": str(content)[:2000],
        }
    )
    shared_memory["messages"] = msgs[-400:]


def researcher_agent(*, subtask: str, shared_memory: dict[str, Any]) -> dict[str, Any]:
    hints = []
    txt = str(subtask or "").lower()
    if "market" in txt or "research" in txt:
        hints.append("Collect external signals before committing execution.")
    if "supplier" in txt:
        hints.append("Compare at least 3 suppliers and verify delivery risk.")
    if "price" in txt:
        hints.append("Benchmark recent pricing patterns and variance range.")
    out = {"agent": "researcher_agent", "subtask": subtask, "insights": hints or ["Gather baseline context and constraints."]}
    _send_message(shared_memory, from_agent="researcher_agent", to_agent="strategist_agent", content="Research context ready.")
    return out


def executor_agent(*, subtask: str, shared_memory: dict[str, Any]) -> dict[str, Any]:
    txt = str(subtask or "").lower()
    executable = {
        "step": str(subtask or "")[:280],
        "validation": "result_ok",
        "needs_confirmation": any(x in txt for x in ("pay", "trade", "delete", "transfer", "contract")),
    }
    out = {"agent": "executor_agent", "subtask": subtask, "execution_outline": executable}
    _send_message(shared_memory, from_agent="executor_agent", to_agent="strategist_agent", content="Execution outline drafted.")
    return out


def strategist_agent(*, subtask: str, shared_memory: dict[str, Any]) -> dict[str, Any]:
    msgs = list(shared_memory.get("messages") or [])
    risk = "medium"
    if any("confirmation" in str(m.get("content") or "").lower() for m in msgs):
        risk = "high"
    strategy = {
        "subtask": subtask,
        "priority": "high" if len(str(subtask or "")) > 80 else "medium",
        "risk": risk,
        "objective": "maximize expected value while controlling downside",
    }
    out = {"agent": "strategist_agent", "strategy": strategy}
    _send_message(shared_memory, from_agent="strategist_agent", to_agent="negotiator_agent", content="Strategy and risk posture prepared.")
    return out


def negotiator_agent(*, subtask: str, shared_memory: dict[str, Any]) -> dict[str, Any]:
    txt = str(subtask or "").lower()
    playbook = []
    if any(k in txt for k in ("supplier", "deal", "price", "contract")):
        playbook.append("Lead with value framing, then anchor terms with fallback options.")
        playbook.append("Use BATNA and set walk-away threshold.")
    else:
        playbook.append("Align stakeholder expectations and secure explicit confirmation.")
    out = {"agent": "negotiator_agent", "negotiation_playbook": playbook}
    _send_message(shared_memory, from_agent="negotiator_agent", to_agent="coordinator", content="Negotiation guidance complete.")
    return out


def _assign_role(subtask: str) -> str:
    t = str(subtask or "").lower()
    if any(k in t for k in ("research", "analyze", "market", "study")):
        return "researcher_agent"
    if any(k in t for k in ("execute", "run", "deploy", "send", "perform")):
        return "executor_agent"
    if any(k in t for k in ("negotiate", "supplier", "deal", "price", "contract")):
        return "negotiator_agent"
    return "strategist_agent"


def _invoke_role(role: str, *, subtask: str, shared_memory: dict[str, Any]) -> dict[str, Any]:
    if role == "researcher_agent":
        return researcher_agent(subtask=subtask, shared_memory=shared_memory)
    if role == "executor_agent":
        return executor_agent(subtask=subtask, shared_memory=shared_memory)
    if role == "negotiator_agent":
        return negotiator_agent(subtask=subtask, shared_memory=shared_memory)
    return strategist_agent(subtask=subtask, shared_memory=shared_memory)


def _critique_outputs(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    critiques: list[dict[str, Any]] = []
    for out in outputs:
        if not isinstance(out, dict):
            continue
        agent = str(out.get("agent") or "unknown")
        issues: list[str] = []
        if agent == "executor_agent" and not isinstance(out.get("execution_outline"), dict):
            issues.append("missing_execution_outline")
        if agent == "strategist_agent" and not isinstance(out.get("strategy"), dict):
            issues.append("missing_strategy")
        if agent == "researcher_agent" and not list(out.get("insights") or []):
            issues.append("missing_research_insights")
        critiques.append({"agent": agent, "issues": issues, "ok": not issues})
    return critiques


def _revise_outputs(outputs: list[dict[str, Any]], critiques: list[dict[str, Any]]) -> list[dict[str, Any]]:
    crit_by_agent = {
        str(c.get("agent") or ""): c for c in critiques if isinstance(c, dict)
    }
    revised: list[dict[str, Any]] = []
    for out in outputs:
        if not isinstance(out, dict):
            continue
        row = dict(out)
        agent = str(row.get("agent") or "")
        c = crit_by_agent.get(agent) or {}
        issues = list(c.get("issues") or [])
        if "missing_execution_outline" in issues:
            row["execution_outline"] = {"step": str(row.get("subtask") or "execute task"), "validation": "result_ok", "needs_confirmation": True}
        if "missing_strategy" in issues:
            row["strategy"] = {
                "subtask": str(row.get("subtask") or ""),
                "priority": "high",
                "risk": "medium",
                "objective": "recover strategic coherence after critique",
            }
        if "missing_research_insights" in issues:
            row["insights"] = ["Collect baseline context and compare alternatives."]
        row["revised_after_critique"] = bool(issues)
        revised.append(row)
    return revised


def _synthesize(outputs: list[dict[str, Any]], shared_memory: dict[str, Any]) -> dict[str, Any]:
    insights: list[str] = []
    execution_outline: list[dict[str, Any]] = []
    strategies: list[dict[str, Any]] = []
    negotiation: list[str] = []
    for o in outputs:
        if not isinstance(o, dict):
            continue
        for i in list(o.get("insights") or []):
            insights.append(str(i)[:260])
        eo = o.get("execution_outline")
        if isinstance(eo, dict):
            execution_outline.append(eo)
        st = o.get("strategy")
        if isinstance(st, dict):
            strategies.append(st)
        for n in list(o.get("negotiation_playbook") or []):
            negotiation.append(str(n)[:260])
    confidence = round(min(0.95, 0.55 + (0.04 * len(outputs))), 3)
    consensus_score = round(min(1.0, confidence + (0.05 if len(strategies) >= 1 and len(execution_outline) >= 1 else 0.0)), 3)
    conflicts: list[str] = []
    if not execution_outline:
        conflicts.append("missing_execution_outline")
    if not strategies:
        conflicts.append("missing_strategy_view")
    conflict_resolution = "validated_consensus" if not conflicts else "fallback_to_conservative_plan"
    prioritized_decision = {
        "priority": "high",
        "action": "execute_primary_plan" if execution_outline else "request_operator_confirmation",
    }
    fallback_option = {
        "action": "run_safe_fallback",
        "path": "notify_and_summarize",
    }
    risk_tradeoff_explanation = (
        "Primary path maximizes expected value; fallback reduces downside and preserves safety guarantees."
    )
    executable_plan: list[dict[str, Any]] = []
    for idx, eo in enumerate(execution_outline[:6], start=1):
        executable_plan.append(
            {
                "step_order": idx,
                "step_kind": "internal_summarize" if bool(eo.get("needs_confirmation")) else "plugin_notify",
                "risk_level": "medium" if bool(eo.get("needs_confirmation")) else "low",
                "payload": {
                    "message": str(eo.get("step") or "execute"),
                    "validation": str(eo.get("validation") or "result_ok"),
                },
            }
        )
    if not executable_plan:
        executable_plan = [
            {
                "step_order": 1,
                "step_kind": "plugin_notify",
                "risk_level": "low",
                "payload": {"title": "Assisted resolution", "body": "Conflicting outputs; fallback plan engaged.", "severity": "warning"},
            }
        ]
    decision = {
        "summary": "Multi-agent synthesis completed.",
        "insights": insights[:12],
        "execution_outline": execution_outline[:12],
        "strategy": strategies[:12],
        "negotiation_playbook": negotiation[:12],
        "message_count": len(list(shared_memory.get("messages") or [])),
        "confidence": confidence,
        "consensus_score": consensus_score,
        "conflicts": conflicts,
        "conflict_resolution": conflict_resolution,
        "prioritized_decision": prioritized_decision,
        "fallback_option": fallback_option,
        "risk_tradeoff_explanation": risk_tradeoff_explanation,
        "executable_plan": executable_plan,
    }
    return decision


def multi_agent_orchestrator(
    *,
    user_id: int,
    organization_id: int,
    goal: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Coordinator:
    - decompose complex goal
    - route subtasks to role agents
    - maintain shared memory and messages
    - merge into final decision
    """
    subtasks = _decompose_goal(goal)
    shared_memory: dict[str, Any] = {
        "created_at": _now_label(),
        "user_id": int(user_id),
        "organization_id": int(organization_id),
        "goal": str(goal or "")[:2000],
        "context": dict(context or {}),
        "messages": [],
    }
    assignments: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for st in subtasks:
        role = _assign_role(st)
        assignments.append({"subtask": st, "assigned_role": role})
        out = _invoke_role(role, subtask=st, shared_memory=shared_memory)
        outputs.append(out)
    # proposal -> critique -> revision -> consensus loop
    proposal_outputs = list(outputs)
    critiques = _critique_outputs(proposal_outputs)
    _send_message(
        shared_memory,
        from_agent="coordinator",
        to_agent="all_agents",
        content=f"Critique round complete: {sum(1 for c in critiques if not c.get('ok'))} agents need revision.",
    )
    revised_outputs = _revise_outputs(proposal_outputs, critiques)
    revised_outputs.append(
        strategist_agent(subtask="Cross-check combined plan coherence", shared_memory=shared_memory)
    )
    final_decision = _synthesize(revised_outputs, shared_memory)
    return {
        "ok": True,
        "complex_goal": _is_complex_goal(goal),
        "subtasks": subtasks,
        "assignments": assignments,
        "shared_memory": shared_memory,
        "outputs": revised_outputs,
        "proposal_outputs": proposal_outputs,
        "critiques": critiques,
        "final_synthesis": final_decision,
    }
