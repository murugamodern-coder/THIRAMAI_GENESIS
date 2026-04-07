"""LangGraph node functions: Architect, Dev, Security (policy), Reviewer, merge, bump_retry."""

from __future__ import annotations

import json
import re
from typing import Literal

from core.actions.registry import all_tools
from core.observability import log_structured
from services.action_policy import PolicyResult, evaluate_tool_action

from core.swarm.blackboard import SwarmState
from core.swarm import llm


def _tool_catalog_snippet() -> str:
    lines = []
    for spec in all_tools():
        lines.append(f"- `{spec.id}` ({spec.domain.value}, {spec.risk.value}): {spec.title}")
    return "\n".join(lines[:80])


def node_architect(state: SwarmState) -> dict:
    """Plan task and enumerate sub-goals (blackboard: plan_markdown, sub_goals)."""
    rid = state.get("request_id") or ""
    sys = (
        "You are the Architect agent in a multi-agent THIRAMAI orchestrator. "
        "Produce a concise execution plan and numbered sub-goals for the user's request. "
        "Stay within THIRAMAI domains: inventory, billing, factory, analytics, compliance, Life OS. "
        "Do not invent external APIs.\n\n"
        "Registered tool ids (reference only):\n"
        f"{_tool_catalog_snippet()}"
    )
    user = f"User message:\n{state.get('user_message', '')}\n\nOrg id: {state.get('organization_id')}"
    try:
        out = llm.groq_chat(system=sys, user=user, max_tokens=2048, temperature=0.15)
    except Exception as exc:
        log_structured("swarm.architect_error", request_id=rid, error=str(exc)[:300])
        out = f"(Architect unavailable: {type(exc).__name__})\n1. Answer user directly with best-effort narrative."
    goals = [g.strip() for g in re.findall(r"^\s*\d+[\).\]]\s*(.+)$", out, re.MULTILINE)]
    if not goals:
        goals = ["Interpret user intent", "Produce safe narrative + valid action_intent if applicable"]
    log_structured("swarm.architect_done", request_id=rid, sub_goals_count=len(goals))
    return {"plan_markdown": out, "sub_goals": goals}


def _parse_tools_json(text: str) -> list[str]:
    m = re.search(r"TOOLS_JSON:\s*(\[[^\]]*\])", text, re.IGNORECASE | re.DOTALL)
    if not m:
        m = re.search(r"TOOLS_JSON:\s*(\[[\s\S]*?\])", text, re.IGNORECASE)
    if m:
        try:
            raw = json.loads(m.group(1))
            if isinstance(raw, list):
                return [str(x).strip() for x in raw if str(x).strip()]
        except json.JSONDecodeError:
            pass
    # fallback: inventory.sell_stock style
    return list(dict.fromkeys(re.findall(r"\b(inventory|billing|factory)\.\w+", text)))


def node_dev(state: SwarmState) -> dict:
    """Propose logic sketch + TOOLS_JSON for downstream policy checks."""
    rid = state.get("request_id") or ""
    fb = state.get("reviewer_feedback") or ""
    retry = int(state.get("retry_count") or 0)
    sys = (
        "You are the Dev agent. Given the Architect plan, describe concrete steps and which "
        "registered tools (if any) should run. Output Markdown plus a single line exactly:\n"
        "TOOLS_JSON: [\"inventory.sell_stock\", ...]\n"
        "Use empty array if no tool calls. Never emit executable code—only descriptions and tool ids.\n\n"
        f"Tool catalog:\n{_tool_catalog_snippet()}"
    )
    user_parts = [
        f"User:\n{state.get('user_message', '')}",
        f"Plan:\n{state.get('plan_markdown', '')}",
        f"Sub-goals: {state.get('sub_goals', [])}",
    ]
    if fb.strip():
        user_parts.append(f"Reviewer requested retry #{retry}:\n{fb}")
    user = "\n\n".join(user_parts)
    try:
        out = llm.groq_chat(system=sys, user=user, max_tokens=4096, temperature=0.2)
    except Exception as exc:
        log_structured("swarm.dev_error", request_id=rid, error=str(exc)[:300])
        out = f"Dev fallback: describe narrative-only response.\nTOOLS_JSON: []\nError: {type(exc).__name__}"
    tools = _parse_tools_json(out)
    log_structured("swarm.dev_done", request_id=rid, tools=",".join(tools[:12]) or "(none)")
    return {"dev_markdown": out, "proposed_tool_ids": tools}


def node_security(state: SwarmState) -> dict:
    """Stage 3 policy engine: evaluate each proposed tool (ALLOW / PROPOSE / BLOCK)."""
    rid = state.get("request_id") or ""
    oid = int(state.get("organization_id") or 0)
    role_level = int(state.get("user_role_level") or 5)
    billing = bool(state.get("billing_paused") or False)
    ids = state.get("proposed_tool_ids") or []
    lines: list[str] = []
    hard = False
    for tid in ids:
        d = evaluate_tool_action(
            tool_id=tid,
            organization_id=oid,
            user_role_level=role_level,
            billing_paused=billing,
        )
        lines.append(f"- `{tid}` → **{d.result.value}** — {d.reason}")
        if d.result == PolicyResult.BLOCK:
            hard = True
    if not ids:
        lines.append("- (no tools proposed — narrative-only path)")
    report = "## Policy engine (Stage 3)\n" + "\n".join(lines)
    log_structured(
        "swarm.security_done",
        request_id=rid,
        hard_block=hard,
        tool_count=len(ids),
    )
    return {"security_report": report, "security_hard_block": hard}


def node_reviewer(state: SwarmState) -> dict:
    """Critique plan + dev + security; PASS or RETRY."""
    rid = state.get("request_id") or ""
    sys = (
        "You are the Reviewer agent. Check coherence, safety, and alignment with the policy report. "
        "If the user request is satisfied without violating BLOCK rules, respond with:\n"
        "VERDICT: PASS\n"
        "Otherwise:\n"
        "VERDICT: RETRY\n"
        "FEEDBACK: <what Dev should fix>\n"
        "If Security shows BLOCK for a required tool, still PASS only if Dev can drop that tool and use narrative-only."
    )
    user = "\n\n".join(
        [
            f"User:\n{state.get('user_message', '')}",
            f"Plan:\n{state.get('plan_markdown', '')}",
            f"Dev:\n{state.get('dev_markdown', '')}",
            state.get("security_report") or "",
        ]
    )
    try:
        out = llm.groq_chat(system=sys, user=user[:100_000], max_tokens=1024, temperature=0.1)
    except Exception as exc:
        log_structured("swarm.reviewer_error", request_id=rid, error=str(exc)[:300])
        return {"reviewer_pass": True, "reviewer_feedback": f"Reviewer skip: {type(exc).__name__}"}
    ok = bool(re.search(r"VERDICT:\s*PASS\b", out, re.IGNORECASE))
    fb_m = re.search(r"FEEDBACK:\s*(.+?)(?:\n\n|\Z)", out, re.IGNORECASE | re.DOTALL)
    fb = fb_m.group(1).strip() if fb_m else out
    log_structured("swarm.reviewer_done", request_id=rid, pass_=ok)
    return {"reviewer_pass": ok, "reviewer_feedback": fb}


def node_merge(state: SwarmState) -> dict:
    """Compile blackboard into a single markdown appendix for the council."""
    parts = [
        "### Swarm blackboard (multi-agent)\n",
        state.get("plan_markdown") or "",
        "\n---\n",
        state.get("dev_markdown") or "",
        "\n---\n",
        state.get("security_report") or "",
    ]
    if state.get("security_hard_block"):
        parts.append(
            "\n> **Note:** Policy BLOCK on at least one tool — downstream narrative must not auto-execute blocked tools.\n"
        )
    if not state.get("reviewer_pass"):
        parts.append(
            f"\n> **Reviewer stopped after max retries.** Last feedback: {state.get('reviewer_feedback', '')[:800]}\n"
        )
    notes = "\n".join(parts).strip()
    return {"swarm_notes": notes}


def node_bump_retry(state: SwarmState) -> dict:
    return {"retry_count": int(state.get("retry_count") or 0) + 1}


def route_after_reviewer(state: SwarmState) -> Literal["merge", "retry"]:
    if state.get("reviewer_pass"):
        return "merge"
    max_r = int(state.get("max_retries") or 2)
    if int(state.get("retry_count") or 0) >= max_r:
        return "merge"
    if state.get("security_hard_block") and int(state.get("retry_count") or 0) > 0:
        return "merge"
    return "retry"
