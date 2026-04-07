"""Tenant-scoped Groq brain endpoint."""

from __future__ import annotations

import asyncio
import os
from typing import Literal

import asset_portal
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, get_current_user, require_permission
from brain import MAX_USER_MESSAGE_CHARS, QueryLengthExceeded, run_brain, run_decision_engine
from core.decision_schema import AIDecision, decision_is_safe
from core.decision_rbac import can_execute_decision
from core.rbac import Permission
from services import action_executor
from services import approval_service as ai_decision_store
from services import audit_log as system_audit
from core.retail_sale_auth import role_may_execute_retail_sale
from core.sale_intent_heuristic import parsed_sell_intent_from_message
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


class ChatQueryBody(BaseModel):
    """JSON body for POST /chat/query (same behavior as GET /chat)."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=MAX_USER_MESSAGE_CHARS,
        description="Message to THIRAMAI (max 5000 characters)",
    )


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
    return await _chat_response(
        body.message.strip(),
        _user,
        vault_passphrase=x_personal_vault_passphrase,
        correlation_id=cid if isinstance(cid, str) else None,
    )
