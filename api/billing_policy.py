"""Billing HTTP routes — policy evaluation + audit (Phase 1 wiring)."""

from __future__ import annotations

from fastapi import HTTPException, Request

from api.dependencies import CurrentUser
from services import billing_guard
from services.action_policy import PolicyResult, evaluate_tool_action
from services.audit_service import log_policy_evaluation


def enforce_billing_tool_policy(
    request: Request,
    user: CurrentUser,
    *,
    tool_id: str,
    action_name: str,
) -> None:
    """
    Log policy decision; raise ``HTTPException(403)`` on BLOCK.

    PROPOSE/ALLOW do not block the HTTP handler — caller continues (HITL may still apply).
    """
    cid = getattr(request.state, "correlation_id", None)
    paused = billing_guard.is_billing_paused(int(user.organization_id))
    decision = evaluate_tool_action(
        tool_id=tool_id,
        organization_id=int(user.organization_id),
        user_role_level=int(user.role_level),
        billing_paused=paused,
    )
    log_policy_evaluation(
        correlation_id=cid if isinstance(cid, str) else None,
        action_name=action_name,
        policy_decision=decision.result.value.upper(),
        user_id=user.id if user.id > 0 else None,
        organization_id=int(user.organization_id),
        tool_id=tool_id,
        reason=decision.reason,
    )
    if decision.result is PolicyResult.BLOCK:
        raise HTTPException(status_code=403, detail=decision.reason)
