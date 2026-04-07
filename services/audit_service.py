"""
Policy + platform audit helpers (``system_audit_logs``).

Uses ``services.audit_log.record_system_audit`` — never store secrets in metadata.
"""

from __future__ import annotations

from typing import Any

from services import audit_log as system_audit


def log_policy_evaluation(
    *,
    correlation_id: str | None,
    action_name: str,
    policy_decision: str,
    user_id: int | None,
    organization_id: int | None,
    tool_id: str,
    reason: str,
    extra: dict[str, Any] | None = None,
) -> int | None:
    """
    Record a policy engine decision (ALLOW / BLOCK / PROPOSE) for SIEM / compliance.

    ``action_name``: stable verb e.g. ``sell_stock``, ``billing_from_production_log``.
    ``policy_decision``: upper-case ALLOW, BLOCK, or PROPOSE.
    """
    meta: dict[str, Any] = {
        "correlation_id": (correlation_id or "")[:128],
        "action_name": (action_name or "")[:128],
        "policy_decision": (policy_decision or "")[:32],
        "tool_id": (tool_id or "")[:128],
        "reason": (reason or "")[:2000],
    }
    if extra:
        meta["extra"] = extra
    outcome = (policy_decision or "unknown").lower()[:32]
    return system_audit.record_system_audit(
        action="policy_evaluation",
        outcome=outcome,
        organization_id=organization_id,
        user_id=user_id if user_id is not None and int(user_id) > 0 else None,
        resource_type="policy",
        metadata=meta,
    )


def log_life_os_mutation(
    *,
    correlation_id: str | None,
    action_name: str,
    user_id: int | None,
    organization_id: int | None,
    resource_type: str,
    extra: dict[str, Any] | None = None,
) -> int | None:
    """Audit personal Life OS writes (habits, missions, health metrics, notes, planner, etc.)."""
    meta: dict[str, Any] = {
        "correlation_id": (correlation_id or "")[:128],
        "action_name": (action_name or "")[:128],
    }
    if extra:
        meta["extra"] = extra
    return system_audit.record_system_audit(
        action="life_os",
        outcome="success",
        organization_id=organization_id,
        user_id=user_id if user_id is not None and int(user_id) > 0 else None,
        resource_type=(resource_type or "life_os")[:64],
        metadata=meta,
    )


def log_business_depth_mutation(
    *,
    correlation_id: str | None,
    action_name: str,
    user_id: int | None,
    organization_id: int | None,
    resource_type: str,
    extra: dict[str, Any] | None = None,
) -> int | None:
    """Audit Business OS writes (departments, staff, attendance, operational expenses)."""
    meta: dict[str, Any] = {
        "correlation_id": (correlation_id or "")[:128],
        "action_name": (action_name or "")[:128],
    }
    if extra:
        meta["extra"] = extra
    return system_audit.record_system_audit(
        action="business_depth",
        outcome="success",
        organization_id=organization_id,
        user_id=user_id if user_id is not None and int(user_id) > 0 else None,
        resource_type=(resource_type or "business_depth")[:64],
        metadata=meta,
    )
