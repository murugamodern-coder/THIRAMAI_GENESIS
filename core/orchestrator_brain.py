"""
Orchestrator brain: classify input, run intent + tools when appropriate, and
apply **safe** autonomy (suggestions always logged; execution only for system
triggers with ``auto_mode``).
"""

from __future__ import annotations

import os
from typing import Any, Literal

from core.agent_base import multi_agent_enabled
from core.brain_output import ActionIntentNone, BrainStructuredResponse
from core.observability import log_structured

Mode = Literal["execute", "respond", "ignore"]
Priority = Literal["high", "medium", "low"]


def _classify_mode_and_priority(user_input: str, resolved: dict[str, Any]) -> tuple[Mode, Priority]:
    intent = str(resolved.get("intent") or "unknown")
    if intent != "unknown":
        if intent in ("sell_inventory", "add_inventory"):
            return "execute", "high"
        return "execute", "medium"

    t = (user_input or "").strip().lower()
    if not t:
        return "ignore", "low"
    if t in ("ok", "thanks", "thank you", "ty", "got it", "👍"):
        return "ignore", "low"

    if "?" in (user_input or ""):
        return "respond", "medium"
    prefixes = (
        "what ",
        "why ",
        "how ",
        "when ",
        "who ",
        "explain ",
        "describe ",
        "tell me ",
        "can you ",
    )
    if any(t.startswith(p) for p in prefixes):
        return "respond", "medium"

    return "respond", "low"


def _resolve_with_optional_llm(text: str) -> dict[str, Any]:
    from core.intent_engine import resolve_intent

    resolved = resolve_intent(text, skip_llm=True)
    if resolved.get("intent") != "unknown":
        return resolved
    if not (text or "").strip():
        return resolved
    groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not groq_key:
        return resolved
    try:
        return resolve_intent(text, skip_llm=False)
    except Exception:
        return resolved


def _markdown_for_exec(user_text: str, exec_result: dict[str, Any], *, autonomous: bool) -> str:
    msg = str(exec_result.get("message") or "").strip()
    ok = bool(exec_result.get("ok"))
    tail = ""
    data = exec_result.get("data")
    if isinstance(data, dict) and data.get("error"):
        tail = f"\n\n`{data.get('error')}`"
    if not msg:
        msg = "Completed." if ok else "Action could not be completed."
    auto = "\n\n_Autonomous (system trigger + auto_mode)._ " if autonomous else ""
    return f"{msg}{tail}{auto}".strip()


def _suggestions_block(suggestions: list[dict[str, Any]]) -> str:
    if not suggestions:
        return ""
    lines = ["**Operator suggestions** (review before acting):"]
    for s in suggestions[:12]:
        lines.append(
            f"- `{s.get('intent')}` — {s.get('reason')} "
            f"(entity={s.get('entity')!r}, qty={s.get('quantity')})"
        )
    return "\n".join(lines)


def run_multi_agent_cycle(context: dict[str, Any]) -> dict[str, Any]:
    """
    CEO-level delegation: run inventory / finance / compliance / growth managers and workers.

    See ``core.multi_agent_cycle.execute_multi_agent_cycle`` for implementation.
    """
    from core.multi_agent_cycle import execute_multi_agent_cycle

    return execute_multi_agent_cycle(context)


def _attach_multi_agent(
    out: dict[str, Any],
    ma_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Append multi-agent audit block to narrative (when present) and always attach ``meta``."""
    if not ma_payload:
        return out
    meta = out.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    meta = {**meta, "multi_agent": ma_payload}
    out["meta"] = meta
    from core.multi_agent_cycle import format_multi_agent_markdown

    md = format_multi_agent_markdown(ma_payload)
    br = out.get("brain_response")
    if br is not None and md:
        out["brain_response"] = br.model_copy(
            update={"narrative": (br.narrative or "").rstrip() + "\n\n" + md}
        )
    return out


def run_orchestrator_brain(
    user_input: str,
    context: dict[str, Any],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """
    Main brain entry for the thin orchestrator layer.

    Returns a dict with:
    - ``handled`` (bool): if True, ``brain_response`` is ready for the API.
    - Standard fields: ``status``, ``mode``, ``priority``, ``action``, ``autonomous``, ``message``.
    """
    from core.autonomy_engine import evaluate_autonomy
    from core.tool_executor import execute_intent

    oid = int(context.get("organization_id") or 0)
    trigger = str(context.get("trigger") or "user").strip().lower()
    auto_mode = bool(context.get("auto_mode"))

    ma_payload: dict[str, Any] | None = None
    if multi_agent_enabled() or str(context.get("include_multi_agent") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        try:
            ma_ctx = {
                **context,
                "request_id": request_id,
                "auto_mode": auto_mode,
            }
            ma_payload = run_multi_agent_cycle(ma_ctx)
        except Exception as exc:
            log_structured(
                "orchestrator_brain.multi_agent_failed",
                request_id=request_id,
                organization_id=oid,
                error_type=type(exc).__name__,
                error=str(exc)[:500],
            )
            ma_payload = None

    text = (user_input or "").strip()
    suggestions: list[dict[str, Any]] = []
    if oid > 0:
        suggestions = evaluate_autonomy(context)
        for s in suggestions:
            log_structured(
                "orchestrator_brain.autonomy_suggestion",
                request_id=request_id,
                organization_id=oid,
                intent=s.get("intent"),
                reason=s.get("reason"),
                entity=s.get("entity"),
            )

    autonomy_results: list[dict[str, Any]] = []
    if trigger == "system" and auto_mode and oid > 0 and suggestions:
        for sug in suggestions[:8]:
            intent_name = str(sug.get("intent") or "")
            if intent_name == "sell_inventory":
                log_structured(
                    "orchestrator_brain.autonomy_skipped",
                    request_id=request_id,
                    reason="financial_intent_blocked",
                    intent=intent_name,
                )
                continue
            if intent_name == "add_inventory":
                qty = sug.get("quantity")
                if qty is None:
                    continue
            intent_data: dict[str, Any] = {
                "intent": intent_name,
                "entity": sug.get("entity") or "",
                "quantity": sug.get("quantity"),
                "confidence": 1.0,
                "source": "autonomy_engine",
            }
            if intent_name == "read_inventory":
                intent_data["read_mode"] = "snapshot"
            ctx_exec = {
                "organization_id": oid,
                "actor_role_name": context.get("actor_role_name"),
                "user_id": context.get("user_id"),
                "role_level": context.get("role_level"),
                "user_message": "",
                "correlation_id": context.get("correlation_id"),
                "experience_source": "orchestrator",
            }
            out = execute_intent(intent_data, ctx_exec)
            autonomy_results.append({"suggestion": sug, "result": out})
            log_structured(
                "orchestrator_brain.autonomy_executed",
                request_id=request_id,
                organization_id=oid,
                intent=intent_name,
                ok=bool(out.get("ok")),
            )

    sug_md = _suggestions_block(suggestions)
    auto_md_parts: list[str] = []
    if autonomy_results:
        for ar in autonomy_results:
            r = ar["result"]
            auto_md_parts.append(_markdown_for_exec("", r, autonomous=True))
        log_structured(
            "orchestrator_brain.autonomy_batch",
            request_id=request_id,
            count=len(autonomy_results),
            organization_id=oid,
        )

    if not text and trigger == "system":
        narrative = "\n\n---\n\n".join([p for p in [sug_md, "\n\n".join(auto_md_parts)] if p]).strip()
        if not narrative:
            narrative = "_No autonomy signals for this organization._"
        log_structured(
            "orchestrator_brain.system_tick",
            request_id=request_id,
            mode="ignore",
            suggestions=len(suggestions),
            executed=len(autonomy_results),
        )
        return _attach_multi_agent(
            {
                "handled": True,
                "fallback_reason": None,
                "status": "success",
                "mode": "ignore",
                "priority": "low",
                "action": "autonomy_tick",
                "autonomous": bool(autonomy_results),
                "message": narrative[:2000],
                "brain_response": BrainStructuredResponse(narrative=narrative, action_intent=ActionIntentNone()),
                "meta": {"suggestions": suggestions, "autonomy_results": autonomy_results},
            },
            ma_payload,
        )

    resolved = _resolve_with_optional_llm(text)
    mode, priority = _classify_mode_and_priority(text, resolved)

    log_structured(
        "orchestrator_brain.decision",
        request_id=request_id,
        mode=mode,
        priority=priority,
        resolved_intent=resolved.get("intent"),
        trigger=trigger,
    )

    if mode == "ignore":
        ack = "Understood." if text else "No input."
        if sug_md:
            ack = f"{ack}\n\n---\n\n{sug_md}"
        return _attach_multi_agent(
            {
                "handled": True,
                "fallback_reason": None,
                "status": "success",
                "mode": "ignore",
                "priority": priority,
                "action": "none",
                "autonomous": False,
                "message": ack,
                "brain_response": BrainStructuredResponse(narrative=ack, action_intent=ActionIntentNone()),
                "meta": {"suggestions": suggestions},
            },
            ma_payload,
        )

    if mode == "respond" and resolved.get("intent") == "unknown":
        return _attach_multi_agent(
            {
                "handled": False,
                "fallback_reason": "council_respond",
                "status": "skipped",
                "mode": "respond",
                "priority": priority,
                "action": "none",
                "autonomous": False,
                "message": "",
                "brain_response": None,
                "meta": {"suggestions": suggestions},
            },
            ma_payload,
        )

    if mode != "execute":
        return _attach_multi_agent(
            {
                "handled": False,
                "fallback_reason": "unexpected_mode",
                "status": "skipped",
                "mode": mode,
                "priority": priority,
                "action": "none",
                "autonomous": False,
                "message": "",
                "brain_response": None,
                "meta": {"suggestions": suggestions},
            },
            ma_payload,
        )

    ctx_exec = {
        "organization_id": oid,
        "actor_role_name": context.get("actor_role_name"),
        "user_id": context.get("user_id"),
        "role_level": context.get("role_level"),
        "user_message": text,
        "correlation_id": context.get("correlation_id"),
        "experience_source": "orchestrator",
    }
    if oid <= 0:
        msg = "**Organization required** — cannot run inventory tools without a tenant id."
        return _attach_multi_agent(
            {
                "handled": True,
                "fallback_reason": None,
                "status": "error",
                "mode": "execute",
                "priority": priority,
                "action": str(resolved.get("intent") or "unknown"),
                "autonomous": False,
                "message": msg,
                "brain_response": BrainStructuredResponse(narrative=msg, action_intent=ActionIntentNone()),
                "meta": {"suggestions": suggestions},
            },
            ma_payload,
        )

    exec_result = execute_intent(resolved, ctx_exec)
    ok = bool(exec_result.get("ok"))
    md = _markdown_for_exec(text, exec_result, autonomous=False)
    if sug_md:
        md = f"{md}\n\n---\n\n{sug_md}"

    return _attach_multi_agent(
        {
            "handled": True,
            "fallback_reason": None,
            "status": "success" if ok else "error",
            "mode": "execute",
            "priority": priority,
            "action": str(exec_result.get("action") or resolved.get("intent") or "unknown"),
            "autonomous": False,
            "message": str(exec_result.get("message") or md)[:4000],
            "brain_response": BrainStructuredResponse(narrative=md, action_intent=ActionIntentNone()),
            "meta": {"suggestions": suggestions, "tool": exec_result},
        },
        ma_payload,
    )
