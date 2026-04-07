"""
Multi-agent pipeline: manager ``decide`` pass → worker dispatch → SaaS factory hints.

Execution is gated by ``context["auto_mode"]``; managers never call tools directly.
"""

from __future__ import annotations

import os
from typing import Any

from core.action_planner import build_action_plan
from core.autonomous_loop import observe_tenant_state
from core.business_decision_engine import analyze_business_decisions
from core.decision_prioritizer import prioritize_decisions
from core.growth_engine import detect_growth_ideas
from core.observability import log_structured, new_request_id
from core.revenue_engine import analyze_revenue
from core.result_tracker import track_results
from core.saas_factory import run_saas_factory
from core.scale_engine import detect_scale_products
from core.strategy_memory import update_strategy_memory

from agents.compliance_manager import ComplianceManager
from agents.finance_manager import FinanceManager
from agents.growth_manager import GrowthManager
from agents.inventory_manager import InventoryManager
from agents.workers import inventory_worker, notification_worker, research_worker


def _truthy(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")


_SAFE_BUSINESS_INTENTS = frozenset({"add_inventory", "read_inventory"})


def _execute_business_action_plan(
    plan: list[dict[str, Any]],
    ctx: dict[str, Any],
    *,
    auto_mode: bool,
    request_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, bool]:
    """Safe tool execution for the AI business layer (suggestions when gated off)."""
    from core.tool_executor import execute_intent

    taken: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    results_tracked = False
    strategy_updated = False
    oid = int(ctx.get("organization_id") or 0)

    for step in plan:
        intent = step.get("intent")
        if step.get("type") == "suggestion" or intent is None:
            held.append({"kind": "action_plan_suggestion", **step})
            continue
        intent_s = str(intent)
        if intent_s not in _SAFE_BUSINESS_INTENTS:
            held.append({**step, "_blocked": "unsafe_intent_for_ai_business_layer", "kind": "action_plan_blocked"})
            log_structured(
                "multi_agent.business_plan_blocked",
                request_id=request_id,
                organization_id=oid,
                intent=intent_s,
            )
            continue
        if not auto_mode:
            held.append({**step, "_held": "auto_mode_off", "kind": "action_plan_held"})
            continue
        if oid <= 0:
            held.append({**step, "_held": "missing_org", "kind": "action_plan_held"})
            continue

        intent_data: dict[str, Any] = {
            "intent": intent_s,
            "entity": step.get("entity") or "",
            "quantity": step.get("quantity"),
            "confidence": 1.0,
            "source": "action_planner",
        }
        if intent_s == "read_inventory":
            intent_data["read_mode"] = "snapshot"

        exec_ctx = {
            "organization_id": oid,
            "actor_role_name": ctx.get("actor_role_name") or "owner",
            "user_id": ctx.get("user_id"),
            "role_level": ctx.get("role_level"),
            "user_message": "",
            "correlation_id": ctx.get("correlation_id") or request_id,
            "experience_source": "ai_business_cycle",
        }
        out = execute_intent(intent_data, exec_ctx)
        taken.append({"source": "ai_business_layer", "step": step, "result": out})
        track_results(step, out, organization_id=oid, request_id=request_id)
        results_tracked = True
        ref = step.get("decision_ref") if isinstance(step.get("decision_ref"), dict) else {
            "decision": step.get("from_decision"),
        }
        update_strategy_memory(
            ref,
            {"ok": bool(out.get("ok")), "detail": out.get("message")},
            organization_id=oid,
            request_id=request_id,
        )
        strategy_updated = True
        log_structured(
            "multi_agent.business_plan_step",
            request_id=request_id,
            organization_id=oid,
            intent=intent_s,
            ok=bool(out.get("ok")),
        )

    return taken, held, results_tracked, strategy_updated


def execute_multi_agent_cycle(context: dict[str, Any]) -> dict[str, Any]:
    """
    Run all managers, aggregate decisions, route to workers, attach SaaS suggestions.

    Returns the API-shaped dict documented on ``run_multi_agent_cycle`` in ``orchestrator_brain``.
    """
    request_id = str(context.get("request_id") or new_request_id())
    ctx = {**context, "request_id": request_id}
    oid = int(ctx.get("organization_id") or 0)
    auto_mode = _truthy(ctx.get("auto_mode"))

    state = observe_tenant_state(ctx)
    ctx["_tenant_state"] = state

    revenue_analysis = analyze_revenue(ctx)
    ctx["_revenue_analysis"] = revenue_analysis

    business_hints = analyze_business_decisions(ctx)
    top_decisions = prioritize_decisions(
        business_hints,
        organization_id=oid,
        request_id=request_id,
    )
    action_plan = build_action_plan(top_decisions, ctx, request_id=request_id)
    growth_ideas = detect_growth_ideas(ctx)
    scale_products = detect_scale_products(ctx)

    managers: list[Any] = [
        InventoryManager(),
        FinanceManager(),
        ComplianceManager(),
        GrowthManager(),
    ]

    agents_summary: list[dict[str, Any]] = []
    all_decisions: list[dict[str, Any]] = []

    for agent in managers:
        obs = agent.observe(ctx)
        ctx[f"_{agent.name}_obs"] = obs
        decisions = agent.decide(ctx)
        for d in decisions:
            d.setdefault("manager", agent.name)
        agent.log_decisions(decisions, ctx, request_id=request_id)
        all_decisions.extend(decisions)
        agents_summary.append(
            {
                "name": agent.name,
                "role": agent.role,
                "observation_keys": list(obs.keys()),
                "decisions": len(decisions),
            }
        )

    log_structured(
        "multi_agent.decisions_ready",
        request_id=request_id,
        organization_id=oid,
        total_decisions=len(all_decisions),
        auto_mode=auto_mode,
    )

    inv_t, inv_s = inventory_worker.run_tasks(all_decisions, ctx, auto_mode=auto_mode, request_id=request_id)
    notif_t, notif_s = notification_worker.run_tasks(all_decisions, ctx, auto_mode=auto_mode, request_id=request_id)
    res_t, res_s = research_worker.run_tasks(all_decisions, ctx, auto_mode=auto_mode, request_id=request_id)

    actions_taken = inv_t + notif_t + res_t
    suggestions = inv_s + notif_s + res_s

    bp_taken, bp_held, results_tracked, strategy_updated = _execute_business_action_plan(
        action_plan,
        ctx,
        auto_mode=auto_mode,
        request_id=request_id,
    )
    actions_taken.extend(bp_taken)
    for h in bp_held:
        suggestions.append(h)

    for row in business_hints:
        suggestions.append(
            {
                "kind": "business_decision",
                "source": "business_decision_engine",
                **row,
            }
        )
    for row in growth_ideas:
        suggestions.append(
            {
                "kind": "growth_idea",
                "source": "growth_engine",
                **row,
            }
        )

    saas_ideas = list(run_saas_factory(ctx))
    seen_products = {str(p.get("product") or "") for p in saas_ideas}
    for sp in scale_products:
        key = str(sp.get("product") or "")
        if not key or key in seen_products:
            continue
        seen_products.add(key)
        saas_ideas.append(
            {
                "product": sp["product"],
                "reason": sp.get("reason", ""),
                "source": sp.get("source", "scale_engine"),
            }
        )

    out = {
        "status": "ai_business_cycle_complete",
        "agents": agents_summary,
        "decisions": all_decisions,
        "top_decisions": top_decisions,
        "action_plan": action_plan,
        "actions_taken": actions_taken,
        "suggestions": suggestions,
        "saas_opportunities": saas_ideas,
        "revenue_analysis": revenue_analysis,
        "results_tracked": results_tracked,
        "strategy_updated": strategy_updated,
        "organization_id": oid,
        "request_id": request_id,
        "auto_mode": auto_mode,
    }
    log_structured(
        "multi_agent.complete",
        request_id=request_id,
        organization_id=oid,
        actions=len(actions_taken),
        suggestions=len(suggestions),
        saas_hints=len(saas_ideas),
        revenue_ok=bool(revenue_analysis.get("ok")),
        business_plan_executed=len(bp_taken),
        results_tracked=results_tracked,
        strategy_updated=strategy_updated,
    )
    return out


def format_multi_agent_markdown(payload: dict[str, Any]) -> str:
    """Compact markdown appendix for the orchestrator narrative."""
    st = payload.get("status") if isinstance(payload, dict) else None
    if not payload or st not in ("ai_business_cycle_complete", "multi_agent_cycle_complete"):
        return ""
    lines = ["---", "**AI business / multi-agent cycle**"]
    rev = payload.get("revenue_analysis") if isinstance(payload.get("revenue_analysis"), dict) else {}
    if rev.get("ok"):
        lines.append(
            f"- **Revenue today (INR):** {rev.get('today_revenue_inr')} · **trend:** `{rev.get('weekly_trend')}`"
        )
        pe = rev.get("profit_estimate") if isinstance(rev.get("profit_estimate"), dict) else {}
        if pe.get("estimated_gross_margin_inr_today") is not None:
            lines.append(
                f"- **Gross margin proxy (today, indicative):** ₹{pe.get('estimated_gross_margin_inr_today')}"
            )
    td = payload.get("top_decisions") or []
    if td:
        lines.append("**Prioritized business decisions:**")
        for row in td[:6]:
            lines.append(
                f"- `{row.get('decision')}` score={row.get('priority_score')} — {row.get('reason', '')[:80]}"
            )
    ap = payload.get("action_plan") or []
    if ap:
        lines.append("**Action plan (execute = gated):**")
        for step in ap[:6]:
            lines.append(
                f"- `{step.get('from_decision')}` → intent={step.get('intent')} type={step.get('type')}"
            )
    for a in payload.get("agents") or []:
        lines.append(f"- _{a.get('name')}_: {a.get('decisions', 0)} decision(s)")
    decs = payload.get("decisions") or []
    if decs:
        lines.append("**Decisions (sample):**")
        for d in decs[:8]:
            lines.append(
                f"- `{d.get('manager')}` → `{d.get('worker')}` · {d.get('reason') or d.get('decision_type')}"
            )
    sug = payload.get("suggestions") or []
    biz = [s for s in sug if isinstance(s, dict) and s.get("kind") == "business_decision"]
    if biz:
        lines.append("**Business decisions (suggest only):**")
        for s in biz[:5]:
            lines.append(f"- `{s.get('decision')}` — {s.get('reason')}")
    gro = [s for s in sug if isinstance(s, dict) and s.get("kind") == "growth_idea"]
    if gro:
        lines.append("**Growth ideas:**")
        for s in gro[:5]:
            lines.append(f"- {s.get('idea')}")

    saas = payload.get("saas_opportunities") or []
    if saas:
        lines.append("**SaaS / scale hints:**")
        for p in saas[:8]:
            lines.append(f"- **{p.get('product')}** — {p.get('reason')}")
    if not _truthy(payload.get("auto_mode")):
        lines.append("_Auto-execute is off; tool actions were held as suggestions._")
    return "\n".join(lines)
