"""Tenant-scoped Groq brain endpoint."""

from __future__ import annotations

import asyncio
import os
from typing import Literal

import asset_portal
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from api.dependencies import CurrentUser, get_current_user, require_permission
from brain import MAX_USER_MESSAGE_CHARS, QueryLengthExceeded, run_brain, run_decision_engine
from core.ai_output_contract import apply_ai_safety_envelope, extract_url_citations
from core.decision_schema import ALLOWED_ACTIONS, AIDecision, decision_is_safe
from core.decision_rbac import can_execute_decision
from core.rbac import Permission
from services import action_executor
from services import approval_service as ai_decision_store
from services import audit_log as system_audit
from core.retail_sale_auth import role_may_execute_retail_sale
from core.sale_intent_heuristic import parsed_sell_intent_from_message
from services.decision_brain_v2 import get_decision_brain_v2
from services.usage_log_service import (
    ACTION_AI_DECISION_APPROVED,
    ACTION_AI_DECISION_EXECUTED,
    ACTION_AI_DECISION_FAILED,
    ACTION_AI_DECISION_PENDING,
    ACTION_AI_DECISION_REJECTED,
    ACTION_AI_DECISION_RESOLVE_FAILED,
    log_usage_sync,
)

router = APIRouter(tags=["AI & Council"])

# PolicyEngine / business_default intents emit actions outside AIDecision's executor allowlist.
# Map bandit arms to safe executor verbs; unmapped → legacy Groq path.
_POLICY_ARM_TO_AIDECISION_ACTION: dict[str, str] = {
    "analyze": "noop",
    "monitor": "noop",
    "alert": "send_alert",
    "no_action": "noop",
}


def _bundle_from_decision_brain_v2(v2: dict) -> dict | None:
    """Convert DecisionBrainV2 unified payload into run_decision_engine_sync-shaped bundle, or None to fall back."""
    if not isinstance(v2, dict):
        return None
    src = str(v2.get("source") or "")
    raw_action = (v2.get("action") or "").strip().lower()
    if not raw_action:
        return None

    if src == "policy_engine":
        mapped = _POLICY_ARM_TO_AIDECISION_ACTION.get(raw_action)
        if not mapped or mapped not in ALLOWED_ACTIONS:
            return None
        executor_action = mapped
    elif src == "safe_fallback":
        mapped = _POLICY_ARM_TO_AIDECISION_ACTION.get(raw_action)
        if not mapped or mapped not in ALLOWED_ACTIONS:
            mapped = "noop" if "noop" in ALLOWED_ACTIONS else None
        if not mapped:
            return None
        executor_action = mapped
    elif src == "legacy_brain":
        if raw_action not in ALLOWED_ACTIONS:
            return None
        executor_action = raw_action
    else:
        return None

    conf_f = float(v2.get("confidence") or 0.0)
    priority: Literal["low", "medium", "high"]
    if conf_f >= 0.8:
        priority = "high"
    elif conf_f >= 0.55:
        priority = "medium"
    else:
        priority = "low"

    reasoning = v2.get("reasoning")
    rationale = (
        " ".join(reasoning).strip()
        if isinstance(reasoning, list)
        else str(reasoning or "").strip()
    )
    if not rationale:
        rationale = f"{src} action={raw_action}"

    meta = v2.get("metadata")
    data: dict = {
        "policy_arm": raw_action,
        "decision_brain_source": src,
        "learning_log_id": v2.get("learning_log_id"),
        "expected_reward": v2.get("expected_reward"),
    }
    if isinstance(meta, dict):
        data["policy_metadata"] = meta
    fr = v2.get("fallback_reason")
    if fr:
        data["fallback_reason"] = str(fr)[:2000]

    dec_dict = {
        "action": executor_action,
        "entity": str(v2.get("action_type") or src),
        "data": data,
        "priority": priority,
        "confidence": conf_f,
        "requires_approval": True,
        "rationale": rationale[:4000],
    }

    ctx_snap: dict = {}
    if isinstance(meta, dict):
        ctx_snap = dict(meta)
    ctx_snap["decision_brain_v2"] = {
        "source": src,
        "policy_arm": raw_action,
        "executor_action": executor_action,
    }

    return {
        "ok": True,
        "decision": dec_dict,
        "context_snapshot": ctx_snap,
        "error": None,
        "validation_error": None,
        "raw_model": "",
    }


class ChatQueryBody(BaseModel):
    """JSON body for POST /chat/query (same behavior as GET /chat)."""

    message: str = Field(
        default="",
        max_length=MAX_USER_MESSAGE_CHARS,
        description="Message to THIRAMAI (max 5000 characters); optional when agent_undo is true",
    )
    agent_mode: bool = Field(False, description="Jarvis tool agent (Groq function calling + confirm flow)")
    agent_confirm: bool = Field(False, description="Execute pending tools after user confirmation")
    agent_pending_id: str | None = Field(None, max_length=256, description="ID from prior agent_mode response")
    agent_undo: bool = Field(False, description="Undo last confirmed Jarvis tool batch (Redis-backed)")
    jarvis_context_org_id: int | None = Field(
        None,
        ge=1,
        description="Optional org scope for Jarvis business tools (must be a membership of the user).",
    )
    agent_confirm_tool_index: int | None = Field(
        None,
        ge=0,
        description="Execute a single pending mutating tool by index (HITL per card).",
    )
    agent_reject_tool_index: int | None = Field(
        None,
        ge=0,
        description="Remove a single pending mutating tool by index without executing it.",
    )
    jarvis_session_id: str | None = Field(
        None,
        max_length=128,
        description="Client-owned Jarvis session key for working + episodic memory continuity.",
    )

    @model_validator(mode="after")
    def _message_required_unless_undo(self) -> ChatQueryBody:
        if self.agent_undo:
            return self
        if self.agent_pending_id and (
            self.agent_confirm_tool_index is not None or self.agent_reject_tool_index is not None
        ):
            return self
        if self.agent_confirm and self.agent_pending_id:
            return self
        if not (self.message or "").strip():
            raise ValueError("message is required unless agent_undo is true")
        return self


class ChatDecisionBody(BaseModel):
    """Phase 3 — JSON decision engine (Groq + business context + execute or HITL)."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=MAX_USER_MESSAGE_CHARS,
        description="User brief for the decision engine",
    )


class DecisionResolveBody(BaseModel):
    """HITL resolve for a pending ``ai_decisions`` row."""

    status: Literal["approved", "rejected"] = Field(
        ...,
        description='Set to "approved" to execute after checks, or "rejected" to discard.',
    )


async def _chat_response(
    query: str,
    _user: CurrentUser,
    *,
    vault_passphrase: str | None = None,
    correlation_id: str | None = None,
) -> JSONResponse:
    from core.ai_input_sanitize import sanitize_user_text

    query = sanitize_user_text(query)
    if parsed_sell_intent_from_message(query) and not role_may_execute_retail_sale(_user.role_name):
        raise HTTPException(
            status_code=403,
            detail="Retail sale requests require an authorized role (e.g. staff or admin).",
        )
    if not (os.getenv("GROQ_API_KEY") or "").strip() or not (os.getenv("TAVILY_API_KEY") or "").strip():
        raise HTTPException(
            status_code=503,
            detail="Missing GROQ_API_KEY or TAVILY_API_KEY in `.env` (project root).",
        )
    try:
        # Groq/Tavily + orchestrator are synchronous; avoid blocking the ASGI event loop.
        structured = await asyncio.to_thread(
            lambda: run_brain(
                query.strip(),
                _user.organization_id,
                actor_role_name=_user.role_name,
                user_id=_user.id,
                vault_passphrase=vault_passphrase,
                correlation_id=correlation_id,
            ),
        )
    except HTTPException:
        raise
    except QueryLengthExceeded as e:
        raise HTTPException(
            status_code=400,
            detail=str(e) or "Query is too long. Keep your brief under 5000 characters.",
        ) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except UnicodeEncodeError:
        raise HTTPException(
            status_code=500,
            detail="Brain encoding error. Check server logs.",
        ) from None
    except Exception as e:
        msg = str(e) if e else "unknown error"
        raise HTTPException(status_code=502, detail=f"Brain error: {msg}") from e

    empire_ux = getattr(structured, "empire_ux", "default")
    if empire_ux == "nominal_silence":
        return JSONResponse(
            content={
                "narrative": "",
                "action_intent": structured.action_intent.model_dump(mode="json"),
                "response": "",
                "quick_actions": [],
                "empire_ux": "nominal_silence",
            }
        )

    narrative = structured.narrative
    new_rows = asset_portal.drain_new_index_rows_for_organization(_user.organization_id)
    quick_actions = asset_portal.quick_action_rows_to_payload(new_rows)
    if new_rows:
        narrative = narrative + "\n\n---\n\n" + asset_portal.format_quick_actions_markdown(new_rows)

    payload: dict = {
        "narrative": narrative,
        "action_intent": structured.action_intent.model_dump(mode="json"),
        "response": narrative,
        "quick_actions": quick_actions,
    }
    if empire_ux != "default":
        payload["empire_ux"] = empire_ux
    sources = extract_url_citations(narrative)
    apply_ai_safety_envelope(payload, narrative=narrative, sources=sources)
    return JSONResponse(content=payload)


@router.post(
    "/chat/decision",
    summary="Phase 3 AI Decision Engine (JSON-only model output → validate → execute or pending approval)",
    description=(
        "Returns structured JSON only (no narrative council). Requires ``ai.query`` permission. "
        "Stores every decision in ``ai_decisions``; executes immediately when ``requires_approval`` is false "
        "and RBAC + safety checks pass."
    ),
)
async def chat_decision(
    request: Request,
    body: ChatDecisionBody,
    _user: CurrentUser = Depends(require_permission(Permission.AI_QUERY)),
) -> JSONResponse:
    cid = getattr(request.state, "correlation_id", None)
    correlation_id = cid if isinstance(cid, str) else None

    bundle: dict | None = None
    try:
        brain = get_decision_brain_v2()
        v2_out = await brain.decide(
            intent="general_decision",
            context={
                "message": body.message.strip(),
                "user_message": body.message.strip(),
                "organization_id": _user.organization_id,
                "actor_role_name": _user.role_name,
                "correlation_id": correlation_id,
            },
            user_id=int(_user.id),
            domain="business",
            organization_id=int(_user.organization_id),
        )
        bundle = _bundle_from_decision_brain_v2(v2_out)
    except Exception:
        bundle = None

    if bundle is None:
        if (os.getenv("THIRAMAI_DISABLE_LEGACY_FALLBACK") or os.getenv("DISABLE_LEGACY_FALLBACK") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            raise HTTPException(
                status_code=503,
                detail="decision unavailable: V2 bundle missing and legacy fallback disabled",
            )
        try:
            bundle = await asyncio.to_thread(
                lambda: run_decision_engine(
                    body.message.strip(),
                    _user.organization_id,
                    actor_role_name=_user.role_name,
                    user_id=_user.id,
                    correlation_id=correlation_id,
                ),
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"decision engine error: {exc}") from exc

    if bundle.get("error") and not bundle.get("decision"):
        raise HTTPException(status_code=503, detail=bundle.get("error") or "decision engine unavailable")

    dec_dict = bundle.get("decision")
    if not dec_dict:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "phase": "decision_engine",
                "validation_error": bundle.get("validation_error"),
                "context_snapshot": bundle.get("context_snapshot"),
                "raw_model": bundle.get("raw_model"),
            },
        )

    try:
        decision = AIDecision.model_validate(dec_dict)
    except Exception as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "phase": "decision_engine", "error": str(exc), "decision": dec_dict},
        )

    rbac_ok, rbac_err = can_execute_decision(role_name=_user.role_name, decision=decision)
    if not rbac_ok:
        raise HTTPException(status_code=403, detail=rbac_err or "forbidden")

    safe_ok, safe_err = decision_is_safe(decision)
    if not safe_ok:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "phase": "decision_engine",
                "safety_error": safe_err,
                "decision": decision.model_dump(mode="json"),
                "context_snapshot": bundle.get("context_snapshot"),
            },
        )

    if decision.requires_approval:
        ins = ai_decision_store.insert_ai_decision(
            organization_id=_user.organization_id,
            user_id=_user.id if _user.id > 0 else None,
            decision=decision,
            status="pending",
            correlation_id=correlation_id,
        )
        if not ins.get("ok"):
            raise HTTPException(status_code=503, detail=ins.get("error") or "cannot persist ai_decision")
        system_audit.record_system_audit(
            action="ai_decision",
            outcome="pending",
            organization_id=_user.organization_id,
            user_id=_user.id if _user.id > 0 else None,
            resource_type="ai_decision",
            metadata={
                "channel": "chat.decision",
                "decision_id": ins.get("id"),
                "action": decision.action,
                "requires_approval": True,
            },
        )
        await asyncio.to_thread(
            lambda: log_usage_sync(
                organization_id=_user.organization_id,
                user_id=_user.id if _user.id > 0 else None,
                action=ACTION_AI_DECISION_PENDING,
                metadata={
                    "decision_id": ins.get("id"),
                    "ai_action": decision.action,
                },
            ),
        )
        return JSONResponse(
            content={
                "ok": True,
                "phase": "decision_engine",
                "status": "pending_approval",
                "decision_id": ins.get("id"),
                "decision": decision.model_dump(mode="json"),
                "execution": None,
                "context_snapshot": bundle.get("context_snapshot"),
            }
        )

    ex = action_executor.execute_decision(
        organization_id=_user.organization_id,
        decision=decision,
        user_id=_user.id if _user.id > 0 else None,
    )
    ins = ai_decision_store.insert_ai_decision(
        organization_id=_user.organization_id,
        user_id=_user.id if _user.id > 0 else None,
        decision=decision,
        status="executed" if ex.get("ok") else "failed",
        correlation_id=correlation_id,
        execution_result=ex.get("result") if ex.get("ok") else None,
        error_message=None if ex.get("ok") else str(ex.get("error") or "execution failed"),
    )
    if not ins.get("ok"):
        raise HTTPException(status_code=503, detail=ins.get("error") or "cannot persist ai_decision")
    system_audit.record_system_audit(
        action="ai_decision",
        outcome="success" if ex.get("ok") else "failure",
        organization_id=_user.organization_id,
        user_id=_user.id if _user.id > 0 else None,
        resource_type="ai_decision",
        metadata={
            "channel": "chat.decision",
            "decision_id": ins.get("id"),
            "action": decision.action,
            "executed": bool(ex.get("ok")),
        },
    )
    _uid = _user.id if _user.id > 0 else None
    _oid = _user.organization_id
    _did = ins.get("id")
    _act = decision.action
    _ok = bool(ex.get("ok"))
    await asyncio.to_thread(
        lambda: log_usage_sync(
            organization_id=_oid,
            user_id=_uid,
            action=ACTION_AI_DECISION_FAILED if not _ok else ACTION_AI_DECISION_EXECUTED,
            metadata={"decision_id": _did, "ai_action": _act, "executed_ok": _ok},
        ),
    )
    return JSONResponse(
        content={
            "ok": bool(ex.get("ok")),
            "phase": "decision_engine",
            "status": "executed" if ex.get("ok") else "failed",
            "decision_id": ins.get("id"),
            "decision": decision.model_dump(mode="json"),
            "execution": ex,
            "context_snapshot": bundle.get("context_snapshot"),
        }
    )


@router.post(
    "/chat/decision/{decision_id}/resolve",
    summary="Resolve a pending AI decision (HITL approve or reject)",
    description=(
        "Requires **hitl.approve**. Approved decisions are validated (RBAC + safety) and executed once; "
        "rejected decisions are closed without execution. Repeating the call is idempotent."
    ),
)
async def chat_decision_resolve(
    decision_id: int,
    body: DecisionResolveBody,
    _user: CurrentUser = Depends(require_permission(Permission.HITL_APPROVE)),
) -> JSONResponse:
    out = ai_decision_store.resolve_ai_decision(
        decision_id=decision_id,
        organization_id=_user.organization_id,
        resolve_status=body.status,
        resolver_user_id=_user.id if _user.id > 0 else None,
        resolver_role_name=_user.role_name,
    )
    if not out.get("ok"):
        await asyncio.to_thread(
            lambda: log_usage_sync(
                organization_id=_user.organization_id,
                user_id=_user.id if _user.id > 0 else None,
                action=ACTION_AI_DECISION_RESOLVE_FAILED,
                metadata={
                    "decision_id": decision_id,
                    "detail": out.get("error"),
                },
            ),
        )
        code = int(out.get("http_status") or 400)
        raise HTTPException(status_code=code, detail=out.get("error") or "resolve failed")
    await asyncio.to_thread(
        lambda: log_usage_sync(
            organization_id=_user.organization_id,
            user_id=_user.id if _user.id > 0 else None,
            action=ACTION_AI_DECISION_APPROVED if body.status == "approved" else ACTION_AI_DECISION_REJECTED,
            metadata={
                "decision_id": out["decision_id"],
                "status": out["status"],
            },
        ),
    )
    payload: dict = {
        "decision_id": out["decision_id"],
        "status": out["status"],
        "execution_result": out.get("execution_result"),
    }
    if out.get("idempotent"):
        payload["idempotent"] = True
    return JSONResponse(content=payload)


@router.get(
    "/chat/decisions/pending",
    summary="List pending AI decisions (Phase 3 ai_decisions)",
    description=(
        "Returns tenant-scoped rows with ``status=pending`` for the Mission Hub. "
        "Requires a valid JWT; same organization isolation as other routes."
    ),
)
async def chat_decisions_pending(
    _user: CurrentUser = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
) -> JSONResponse:
    if int(_user.id) <= 0:
        raise HTTPException(status_code=400, detail="Valid user id required")
    out = ai_decision_store.list_pending_ai_decisions(
        organization_id=_user.organization_id,
        limit=limit,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=503, detail=out.get("error") or "unavailable")
    return JSONResponse(content=out)


@router.get(
    "/chat",
    summary="Run THIRAMAI brain (council + structured action_intent)",
    description="Tenant-scoped vault + Groq + Tavily. Rate-limited per IP.",
)
async def chat(
    request: Request,
    query: str = Query(
        ...,
        min_length=1,
        max_length=MAX_USER_MESSAGE_CHARS,
        description="Message to THIRAMAI (max 5000 characters)",
    ),
    _user: CurrentUser = Depends(get_current_user),
    x_personal_vault_passphrase: str | None = Header(
        default=None,
        alias="X-Personal-Vault-Passphrase",
        description="Optional. Unlocks encrypted Life OS fields in the executive pack (never logged).",
    ),
) -> JSONResponse:
    cid = getattr(request.state, "correlation_id", None)
    return await _chat_response(
        query.strip(),
        _user,
        vault_passphrase=x_personal_vault_passphrase,
        correlation_id=cid if isinstance(cid, str) else None,
    )


@router.post(
    "/chat/query",
    summary="Run THIRAMAI brain (JSON body)",
    description=(
        "Same as GET /chat; message in JSON body. Requires a **valid, unexpired** Bearer JWT "
        "(validated in middleware + dependency). Per-user rate limit: "
        "`THIRAMAI_RL_CHAT_QUERY_PER_USER_PER_MINUTE` (default 5). "
        "Messages that look like a retail sale (heuristic) return **403** for roles that cannot sell "
        "(e.g. **customer**). Retail ``sell_stock`` auto-exec requires **admin** or **staff**."
    ),
)
async def chat_query(
    request: Request,
    body: ChatQueryBody,
    _user: CurrentUser = Depends(get_current_user),
    x_personal_vault_passphrase: str | None = Header(
        default=None,
        alias="X-Personal-Vault-Passphrase",
        description="Optional. Unlocks encrypted Life OS notes for this chat turn.",
    ),
) -> JSONResponse:
    cid = getattr(request.state, "correlation_id", None)
    if body.agent_undo:
        from services import jarvis_agent_service as jarvis

        payload = await asyncio.to_thread(lambda: jarvis.undo_last_action(user=_user))
        return JSONResponse(content=payload)
    if body.agent_mode:
        from core.ai_usage_limits import consume_llm_units
        from services.product_plans import organization_plan_sync, plan_allows

        raw_plan = organization_plan_sync(int(_user.organization_id))
        if not plan_allows(raw_plan, "advanced_ai"):
            raise HTTPException(
                status_code=402,
                detail="Jarvis agent (tool-calling) requires Pro or Business. Open /pricing to upgrade.",
            )
        allowed, umsg = consume_llm_units(int(_user.id), plan=raw_plan)
        if not allowed:
            raise HTTPException(status_code=429, detail=umsg or "LLM budget exceeded")
        from services import jarvis_agent_service as jarvis

        payload = await asyncio.to_thread(
            lambda: jarvis.run_agent(
                message=(body.message or "").strip(),
                user=_user,
                agent_confirm=bool(body.agent_confirm),
                agent_pending_id=body.agent_pending_id,
                context_organization_id=body.jarvis_context_org_id,
                agent_confirm_tool_index=body.agent_confirm_tool_index,
                agent_reject_tool_index=body.agent_reject_tool_index,
                jarvis_session_id=body.jarvis_session_id,
            ),
        )
        return JSONResponse(content=payload)
    return await _chat_response(
        body.message.strip(),
        _user,
        vault_passphrase=x_personal_vault_passphrase,
        correlation_id=cid if isinstance(cid, str) else None,
    )
