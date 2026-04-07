"""Registered background jobs for the Sovereign Action Engine."""

from __future__ import annotations

from typing import Any

from core.recursive_learning import compact_payload_for_learning, record_learning_log
from services import billing_service
from services.execution_engine import BRAIN_ACTION_INTENT_TYPE, execute_approved_intent_payload

from workers.runner import run_with_idempotency


def _log_hitl_execution(
    *,
    organization_id: int,
    outcome: str,
    action_type: str,
    base_ctx: dict[str, Any],
    result: dict[str, Any],
    user_feedback: str,
    approval_id: str | None,
    resolved_by_user_id: int | None = None,
) -> None:
    if organization_id <= 0:
        return
    try:
        record_learning_log(
            organization_id=organization_id,
            outcome=outcome,
            action_type=action_type,
            context=base_ctx,
            result=result,
            user_feedback=user_feedback,
            approval_id=approval_id,
            resolved_by_user_id=resolved_by_user_id,
        )
    except Exception:
        pass


def job_execute_approved_invoice(
    payload: dict[str, Any],
    idempotency_key: str,
    *,
    approval_id: str | None = None,
    user_feedback: str = "",
    resolved_by_user_id: int | None = None,
) -> dict[str, Any]:
    """Run after HITL YES — PDF, inventory deduction, index (idempotent)."""
    oid = int(payload.get("organization_id") or 0)
    action_type = "issue_invoice"
    base_ctx: dict[str, Any] = {
        "payload_outline": compact_payload_for_learning(payload),
        "idempotency_key": idempotency_key,
    }
    if approval_id:
        base_ctx["approval_id"] = approval_id

    def _work() -> dict[str, Any]:
        return billing_service.execute_approved_invoice_payload(payload)

    try:
        ok, result, msg = run_with_idempotency(
            _work,
            idempotency_key=idempotency_key,
            action_type="issue_invoice",
            risk_tier="high",
        )
    except Exception as exc:
        _log_hitl_execution(
            organization_id=oid,
            outcome="execution_failed",
            action_type=action_type,
            base_ctx=base_ctx,
            result={"error": str(exc), "error_type": type(exc).__name__},
            user_feedback=user_feedback,
            approval_id=approval_id,
            resolved_by_user_id=resolved_by_user_id,
        )
        raise

    if not ok and msg == "duplicate":
        _log_hitl_execution(
            organization_id=oid,
            outcome="duplicate_skip",
            action_type=action_type,
            base_ctx=base_ctx,
            result={"message": "idempotent_skip"},
            user_feedback=user_feedback,
            approval_id=approval_id,
            resolved_by_user_id=resolved_by_user_id,
        )
        return {"ok": True, "duplicate": True, "message": "idempotent_skip"}

    res = result if isinstance(result, dict) else {"ok": False, "error": "no_result"}
    _log_hitl_execution(
        organization_id=oid,
        outcome="executed",
        action_type=action_type,
        base_ctx=base_ctx,
        result=res,
        user_feedback=user_feedback,
        approval_id=approval_id,
        resolved_by_user_id=resolved_by_user_id,
    )
    return res


def job_execute_brain_intent(
    payload: dict[str, Any],
    organization_id: int,
    idempotency_key: str,
    *,
    approval_id: str | None = None,
    user_feedback: str = "",
    resolved_by_user_id: int | None = None,
) -> dict[str, Any]:
    """Run after HITL YES on ``brain_action_intent`` approvals (inventory / invoice from Stage 5)."""
    oid = int(organization_id)
    base_ctx: dict[str, Any] = {
        "payload_outline": compact_payload_for_learning(payload),
        "idempotency_key": idempotency_key,
        "organization_id": oid,
    }
    if approval_id:
        base_ctx["approval_id"] = approval_id

    def _work() -> dict[str, Any]:
        return execute_approved_intent_payload(
            payload,
            organization_id=oid,
            resolved_by_user_id=resolved_by_user_id,
            correlation_id=None,
        )

    try:
        ok, result, msg = run_with_idempotency(
            _work,
            idempotency_key=idempotency_key,
            action_type=BRAIN_ACTION_INTENT_TYPE,
            risk_tier="high",
        )
    except Exception as exc:
        _log_hitl_execution(
            organization_id=oid,
            outcome="execution_failed",
            action_type=BRAIN_ACTION_INTENT_TYPE,
            base_ctx=base_ctx,
            result={"error": str(exc), "error_type": type(exc).__name__},
            user_feedback=user_feedback,
            approval_id=approval_id,
            resolved_by_user_id=resolved_by_user_id,
        )
        raise

    if not ok and msg == "duplicate":
        _log_hitl_execution(
            organization_id=oid,
            outcome="duplicate_skip",
            action_type=BRAIN_ACTION_INTENT_TYPE,
            base_ctx=base_ctx,
            result={"message": "idempotent_skip"},
            user_feedback=user_feedback,
            approval_id=approval_id,
            resolved_by_user_id=resolved_by_user_id,
        )
        return {"ok": True, "duplicate": True, "message": "idempotent_skip"}

    res = result if isinstance(result, dict) else {"ok": False, "error": "no_result"}
    _log_hitl_execution(
        organization_id=oid,
        outcome="executed",
        action_type=BRAIN_ACTION_INTENT_TYPE,
        base_ctx=base_ctx,
        result=res,
        user_feedback=user_feedback,
        approval_id=approval_id,
        resolved_by_user_id=resolved_by_user_id,
    )
    return res
