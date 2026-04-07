"""
Policy kernel — ALLOW / PROPOSE / BLOCK for tool and side-effect execution (AI OS Phase 1).

Callers pass tool metadata from ``core.actions.registry`` and runtime flags (billing pause, role, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.actions.registry import ToolRisk, ToolSpec, get_tool


class PolicyResult(str, Enum):
    """Outcome of policy evaluation for a single action."""

    ALLOW = "allow"
    PROPOSE = "propose"
    BLOCK = "block"


@dataclass(frozen=True)
class PolicyDecision:
    result: PolicyResult
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _apply_hitl_to_allow(
    decision: PolicyDecision,
    spec: ToolSpec,
    organization_id: int,
    tool_id: str,
) -> PolicyDecision:
    """Tighten ALLOW → PROPOSE when HITL weights indicate higher scrutiny."""
    if decision.result is not PolicyResult.ALLOW:
        return decision
    if spec.risk is ToolRisk.LOW:
        return decision
    try:
        from services import hitl_rule_weights as hw

        mult = hw.strictness_multiplier(int(organization_id), tool_id)
    except Exception:
        return decision
    if mult < 1.06:
        return decision
    return PolicyDecision(
        PolicyResult.PROPOSE,
        f"HITL feedback increased scrutiny (weight={mult:.2f}) — seek approval before auto-execution",
        {**decision.metadata, "hitl_multiplier": mult, "tool_id": tool_id},
    )


def evaluate_tool_action(
    *,
    tool_id: str,
    organization_id: int,
    user_role_level: int,
    billing_paused: bool = False,
    hitl_required_override: bool | None = None,
) -> PolicyDecision:
    """
    Evaluate whether an action may run automatically, must be proposed for approval, or is blocked.

    ``user_role_level``: lower number = higher privilege (owner=1, customer=5) per ``api.dependencies``.
    """
    oid = int(organization_id)
    if oid <= 0:
        return PolicyDecision(PolicyResult.BLOCK, "invalid organization_id", {"tool_id": tool_id})

    try:
        from services.experience_buffer import is_blocked_by_critical_mistake

        blocked, cm_reason = is_blocked_by_critical_mistake(oid, tool_id)
    except Exception:
        blocked, cm_reason = False, ""
    if blocked:
        return PolicyDecision(
            PolicyResult.BLOCK,
            cm_reason or "CRITICAL_MISTAKE — human override blocks this tool for this organization",
            {"tool_id": tool_id, "organization_id": oid, "critical_mistake": True},
        )

    def _fin(d: PolicyDecision) -> PolicyDecision:
        sp = get_tool(tool_id)
        if sp is None:
            return d
        return _apply_hitl_to_allow(d, sp, oid, tool_id)

    spec = get_tool(tool_id)
    if spec is None:
        return PolicyDecision(
            PolicyResult.BLOCK,
            f"unknown tool_id {tool_id!r} — not registered",
            {"tool_id": tool_id},
        )

    if billing_paused and spec.respects_factory_billing_hold:
        return PolicyDecision(
            PolicyResult.BLOCK,
            "factory billing hold — mutating business actions are blocked until hold is cleared",
            {"tool_id": tool_id, "organization_id": oid},
        )

    if user_role_level >= 5:
        return PolicyDecision(
            PolicyResult.BLOCK,
            "role cannot execute operational tools",
            {"tool_id": tool_id, "role_level": user_role_level},
        )

    if hitl_required_override is True:
        return PolicyDecision(
            PolicyResult.PROPOSE,
            "human approval required (override)",
            {"tool_id": tool_id},
        )

    if spec.risk is ToolRisk.CRITICAL:
        return PolicyDecision(
            PolicyResult.PROPOSE,
            "critical-risk tool — requires sovereign / HITL approval before execution",
            {"tool_id": tool_id, "domain": spec.domain},
        )

    if spec.risk is ToolRisk.HIGH:
        if user_role_level <= 2:
            return _fin(
                PolicyDecision(
                    PolicyResult.ALLOW,
                    "high-risk tool allowed for owner/manager",
                    {"tool_id": tool_id},
                )
            )
        return PolicyDecision(
            PolicyResult.PROPOSE,
            "high-risk tool — propose to owner/manager",
            {"tool_id": tool_id, "role_level": user_role_level},
        )

    if spec.risk is ToolRisk.MEDIUM:
        if user_role_level <= 3:
            return _fin(
                PolicyDecision(PolicyResult.ALLOW, "medium risk — supervisor or above", {"tool_id": tool_id})
            )
        return PolicyDecision(
            PolicyResult.PROPOSE,
            "medium-risk tool — needs supervisor+ or approval",
            {"tool_id": tool_id},
        )

    return _fin(PolicyDecision(PolicyResult.ALLOW, "low risk — allowed", {"tool_id": tool_id}))
