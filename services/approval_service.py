"""
Phase 3 — persist AI decisions (``ai_decisions``) for approval and audit.

Distinct from ``approval_store`` (HITL ``approvals`` table for legacy flows).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import AiDecision
from core.decision_schema import AIDecision, decision_is_safe
from core.decision_rbac import can_execute_decision
from services import action_executor
from services import audit_log as system_audit


def insert_ai_decision(
    *,
    organization_id: int,
    user_id: int | None,
    decision: AIDecision,
    status: str = "pending",
    correlation_id: str | None = None,
    execution_result: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Insert one row; returns ``{ok, id}`` or ``{ok: False, error}``."""
    oid = int(organization_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    payload = decision.model_dump(mode="json")
    with factory() as session:
        with session.begin():
            row = AiDecision(
                organization_id=oid,
                user_id=user_id if user_id and int(user_id) > 0 else None,
                action=decision.action,
                entity=decision.entity or "",
                priority=decision.priority,
                requires_approval=bool(decision.requires_approval),
                status=status[:32],
                payload=payload,
                execution_result=execution_result,
                error_message=(error_message or "")[:8000] or None,
                correlation_id=(correlation_id or "")[:128] or None,
            )
            session.add(row)
            session.flush()
            rid = int(row.id)
    return {"ok": True, "id": rid}


def list_pending_ai_decisions(*, organization_id: int, limit: int = 50) -> dict[str, Any]:
    oid = int(organization_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    lim = max(1, min(int(limit), 200))
    with factory() as session:
        rows = list(
            session.scalars(
                select(AiDecision)
                .where(AiDecision.organization_id == oid, AiDecision.status == "pending")
                .order_by(AiDecision.id.desc())
                .limit(lim)
            ).all()
        )
    items = [
        {
            "id": int(r.id),
            "action": r.action,
            "entity": r.entity,
            "priority": r.priority,
            "requires_approval": r.requires_approval,
            "status": r.status,
            "payload": r.payload,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "correlation_id": r.correlation_id,
        }
        for r in rows
    ]
    return {"ok": True, "items": items}


def update_ai_decision_status(
    *,
    decision_id: int,
    organization_id: int,
    status: str,
    execution_result: dict[str, Any] | None = None,
    error_message: str | None = None,
    resolved_by_user_id: int | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    did = int(decision_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    with factory() as session:
        with session.begin():
            row = session.get(AiDecision, did)
            if row is None or int(row.organization_id) != oid:
                return {"ok": False, "error": "decision not found"}
            row.status = status[:32]
            row.execution_result = execution_result
            row.error_message = (error_message or "")[:8000] or None
            row.resolved_at = datetime.now(timezone.utc)
            if resolved_by_user_id and resolved_by_user_id > 0:
                row.resolved_by_user_id = int(resolved_by_user_id)
    return {"ok": True, "id": did}


def _execution_message_for_row(row: AiDecision) -> str:
    er = row.execution_result
    if isinstance(er, dict):
        if er.get("message"):
            return str(er["message"])[:2000]
        if er.get("id") is not None:
            return f"completed (id={er['id']})"
    return "executed"


def _idempotent_resolve_payload(row: AiDecision) -> dict[str, Any]:
    did = int(row.id)
    st = (row.status or "").lower()
    if st == "rejected":
        return {
            "ok": True,
            "decision_id": did,
            "status": "rejected",
            "execution_result": None,
            "idempotent": True,
        }
    if st == "executing":
        return {
            "ok": False,
            "error": "decision is being executed; retry shortly",
            "http_status": 409,
            "decision_id": did,
        }
    if st == "executed":
        return {
            "ok": True,
            "decision_id": did,
            "status": "approved",
            "execution_result": {
                "success": True,
                "message": _execution_message_for_row(row),
            },
            "idempotent": True,
        }
    if st == "failed":
        return {
            "ok": True,
            "decision_id": did,
            "status": "approved",
            "execution_result": {
                "success": False,
                "message": (row.error_message or "execution failed")[:2000],
            },
            "idempotent": True,
        }
    return {"ok": False, "error": f"unexpected decision status: {st}"}


def resolve_ai_decision(
    *,
    decision_id: int,
    organization_id: int,
    resolve_status: str,
    resolver_user_id: int | None,
    resolver_role_name: str,
) -> dict[str, Any]:
    """
    Approve or reject a pending ``ai_decisions`` row (HITL).

    * **approved**: validate payload → ``action_executor.execute_decision`` → ``executed`` / ``failed``
    * **rejected**: ``rejected`` only (no execution)
    * Idempotent: already terminal rows return cached outcome without re-executing.
    """
    oid = int(organization_id)
    did = int(decision_id)
    rs = (resolve_status or "").strip().lower()
    if rs not in ("approved", "rejected"):
        return {"ok": False, "error": 'status must be "approved" or "rejected"'}

    uid = resolver_user_id if resolver_user_id and int(resolver_user_id) > 0 else None
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    payload_copy: dict[str, Any] = {}
    action_copy = ""

    with factory() as session:
        with session.begin():
            row = session.get(AiDecision, did)
            if row is None or int(row.organization_id) != oid:
                return {"ok": False, "error": "decision not found", "http_status": 404}

            cur = (row.status or "").lower()
            if cur in ("executed", "failed", "rejected"):
                return _idempotent_resolve_payload(row)

            if cur == "executing":
                return _idempotent_resolve_payload(row)

            if cur != "pending":
                return {"ok": False, "error": f"decision not resolvable from status {cur!r}"}

            if rs == "rejected":
                row.status = "rejected"
                row.resolved_at = datetime.now(timezone.utc)
                if uid:
                    row.resolved_by_user_id = uid
                action_copy = row.action
            else:
                payload_copy = dict(row.payload) if isinstance(row.payload, dict) else {}
                action_copy = row.action
                row.status = "executing"
                row.resolved_at = datetime.now(timezone.utc)
                if uid:
                    row.resolved_by_user_id = uid

    if rs == "rejected":
        system_audit.record_system_audit(
            action="ai_decision_resolve",
            outcome="success",
            organization_id=oid,
            user_id=uid,
            resource_type="ai_decision",
            metadata={
                "channel": "approval_service.resolve",
                "decision_id": did,
                "action": action_copy,
                "resolver": uid,
                "result": "rejected",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        return {
            "ok": True,
            "decision_id": did,
            "status": "rejected",
            "execution_result": None,
            "idempotent": False,
        }

    try:
        decision = AIDecision.model_validate(payload_copy)
    except Exception as exc:
        with factory() as session:
            with session.begin():
                r3 = session.get(AiDecision, did)
                if r3 and int(r3.organization_id) == oid and (r3.status or "").lower() == "executing":
                    r3.status = "failed"
                    r3.error_message = f"invalid payload: {exc}"[:8000]
        system_audit.record_system_audit(
            action="ai_decision_resolve",
            outcome="failure",
            organization_id=oid,
            user_id=uid,
            resource_type="ai_decision",
            metadata={
                "channel": "approval_service.resolve",
                "decision_id": did,
                "action": action_copy,
                "resolver": uid,
                "result": "validation_error",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        return {
            "ok": True,
            "decision_id": did,
            "status": "approved",
            "execution_result": {"success": False, "message": f"invalid payload: {exc}"},
            "idempotent": False,
        }

    rbac_ok, rbac_err = can_execute_decision(role_name=resolver_role_name, decision=decision)
    if not rbac_ok:
        with factory() as session:
            with session.begin():
                r3 = session.get(AiDecision, did)
                if r3 and int(r3.organization_id) == oid and (r3.status or "").lower() == "executing":
                    r3.status = "failed"
                    r3.error_message = (rbac_err or "forbidden")[:8000]
        system_audit.record_system_audit(
            action="ai_decision_resolve",
            outcome="failure",
            organization_id=oid,
            user_id=uid,
            resource_type="ai_decision",
            metadata={
                "channel": "approval_service.resolve",
                "decision_id": did,
                "action": decision.action,
                "resolver": uid,
                "result": "rbac_denied",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        return {
            "ok": True,
            "decision_id": did,
            "status": "approved",
            "execution_result": {"success": False, "message": rbac_err or "forbidden"},
            "idempotent": False,
        }

    safe_ok, safe_err = decision_is_safe(decision)
    if not safe_ok:
        with factory() as session:
            with session.begin():
                r3 = session.get(AiDecision, did)
                if r3 and int(r3.organization_id) == oid and (r3.status or "").lower() == "executing":
                    r3.status = "failed"
                    r3.error_message = (safe_err or "unsafe")[:8000]
        system_audit.record_system_audit(
            action="ai_decision_resolve",
            outcome="failure",
            organization_id=oid,
            user_id=uid,
            resource_type="ai_decision",
            metadata={
                "channel": "approval_service.resolve",
                "decision_id": did,
                "action": decision.action,
                "resolver": uid,
                "result": "unsafe",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        return {
            "ok": True,
            "decision_id": did,
            "status": "approved",
            "execution_result": {"success": False, "message": safe_err or "unsafe"},
            "idempotent": False,
        }

    ex = action_executor.execute_decision(
        organization_id=oid,
        decision=decision,
        user_id=uid,
    )

    ok_exec = bool(ex.get("ok"))
    msg_ok = "executed"
    if ok_exec:
        res = ex.get("result")
        if isinstance(res, dict):
            if res.get("message"):
                msg_ok = str(res["message"])[:2000]
            elif res.get("purchase_order_id") or res.get("id"):
                msg_ok = "Purchase order created" if decision.action in ("reorder_stock", "create_purchase_order") else "completed"
    else:
        msg_ok = str(ex.get("error") or "execution failed")[:2000]

    with factory() as session:
        with session.begin():
            r3 = session.get(AiDecision, did)
            if r3 is None or int(r3.organization_id) != oid:
                return {"ok": False, "error": "decision not found", "http_status": 404}
            if (r3.status or "").lower() != "executing":
                return _idempotent_resolve_payload(r3)
            r3.status = "executed" if ok_exec else "failed"
            r3.execution_result = ex.get("result") if ok_exec else None
            r3.error_message = None if ok_exec else msg_ok[:8000]

    system_audit.record_system_audit(
        action="ai_decision_resolve",
        outcome="success" if ok_exec else "failure",
        organization_id=oid,
        user_id=uid,
        resource_type="ai_decision",
        metadata={
            "channel": "approval_service.resolve",
            "decision_id": did,
            "action": decision.action,
            "resolver": uid,
            "result": "executed" if ok_exec else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

    return {
        "ok": True,
        "decision_id": did,
        "status": "approved",
        "execution_result": {"success": ok_exec, "message": msg_ok},
        "idempotent": False,
    }
