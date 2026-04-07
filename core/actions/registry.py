"""
Central registry of executable tools / capabilities (Phase 1 — inventory, billing, factory).

Orchestrator, workers, and HTTP routes should reference ``tool_id`` strings defined here for policy + audit alignment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolDomain(str, Enum):
    INVENTORY = "inventory"
    BILLING = "billing"
    FACTORY = "factory"


class ToolRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ToolSpec:
    """Description of a tool the AI or automation may invoke."""

    id: str
    domain: ToolDomain
    title: str
    risk: ToolRisk
    description: str = ""
    respects_factory_billing_hold: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(spec: ToolSpec) -> None:
    if spec.id in _REGISTRY:
        raise ValueError(f"duplicate tool id: {spec.id!r}")
    _REGISTRY[spec.id] = spec


def get_tool(tool_id: str) -> ToolSpec | None:
    return _REGISTRY.get(tool_id)


def all_tools() -> list[ToolSpec]:
    return sorted(_REGISTRY.values(), key=lambda s: (s.domain.value, s.id))


def _register_defaults() -> None:
    if _REGISTRY:
        return

    # --- Inventory ---
    register_tool(
        ToolSpec(
            id="inventory.sell_stock",
            domain=ToolDomain.INVENTORY,
            title="Retail sell / stock deduction",
            risk=ToolRisk.HIGH,
            description="Deduct inventory and create a bill row (POS flow).",
        )
    )
    register_tool(
        ToolSpec(
            id="inventory.adjust_quantity",
            domain=ToolDomain.INVENTORY,
            title="Manual inventory adjustment",
            risk=ToolRisk.MEDIUM,
            description="Apply delta to stock for a SKU/location.",
        )
    )
    register_tool(
        ToolSpec(
            id="inventory.read_stock",
            domain=ToolDomain.INVENTORY,
            title="Read stock levels",
            risk=ToolRisk.LOW,
            description="Query quantities — read-only.",
            respects_factory_billing_hold=False,
        )
    )

    # --- Billing ---
    register_tool(
        ToolSpec(
            id="billing.issue_invoice",
            domain=ToolDomain.BILLING,
            title="Issue / post invoice from HITL approval",
            risk=ToolRisk.CRITICAL,
            description="Finalize invoice PDF and accounting-related side effects.",
        )
    )
    register_tool(
        ToolSpec(
            id="billing.production_log_invoice",
            domain=ToolDomain.BILLING,
            title="Invoice from production log",
            risk=ToolRisk.HIGH,
            description="Queue or run billing from production log + inventory SKU.",
        )
    )
    register_tool(
        ToolSpec(
            id="billing.resolve_approval",
            domain=ToolDomain.BILLING,
            title="Resolve HITL approval",
            risk=ToolRisk.HIGH,
            description="Approve or reject pending approval rows.",
        )
    )
    register_tool(
        ToolSpec(
            id="billing.apply_approved_invoice_job",
            domain=ToolDomain.BILLING,
            title="Schedule approved invoice execution job",
            risk=ToolRisk.LOW,
            description="After HITL YES — enqueue issue_invoice worker (sovereign already approved).",
            respects_factory_billing_hold=True,
        )
    )
    register_tool(
        ToolSpec(
            id="billing.apply_approved_brain_intent_job",
            domain=ToolDomain.BILLING,
            title="Schedule approved brain intent execution job",
            risk=ToolRisk.MEDIUM,
            description="After HITL YES — enqueue Stage-5 intent execution.",
            respects_factory_billing_hold=True,
        )
    )
    register_tool(
        ToolSpec(
            id="billing.queue_brain_intent",
            domain=ToolDomain.BILLING,
            title="Queue brain action intent for HITL",
            risk=ToolRisk.HIGH,
            description="Create pending approval for Stage-5 action_intent.",
            respects_factory_billing_hold=True,
        )
    )
    register_tool(
        ToolSpec(
            id="billing.generate_invoice_pdf",
            domain=ToolDomain.BILLING,
            title="Generate invoice PDF and sales history entry",
            risk=ToolRisk.MEDIUM,
            description="Direct PDF + master_index append (no HITL queue).",
            respects_factory_billing_hold=True,
        )
    )

    # --- Factory OS ---
    register_tool(
        ToolSpec(
            id="factory.stage2_machine_failure",
            domain=ToolDomain.FACTORY,
            title="Declare Stage 2 machine failure",
            risk=ToolRisk.HIGH,
            description="Mark income-stage project machine down; triggers billing hold + emergency alert.",
        )
    )
    register_tool(
        ToolSpec(
            id="factory.clear_stage2_failure",
            domain=ToolDomain.FACTORY,
            title="Clear Stage 2 machine failure",
            risk=ToolRisk.MEDIUM,
            description="Clear failure flag; may resume billing.",
        )
    )
    register_tool(
        ToolSpec(
            id="factory.assign_staff",
            domain=ToolDomain.FACTORY,
            title="Assign staff to project stage",
            risk=ToolRisk.LOW,
            description="Manpower mapping for lifecycle projects.",
            respects_factory_billing_hold=False,
        )
    )
    register_tool(
        ToolSpec(
            id="factory.set_revival_cost",
            domain=ToolDomain.FACTORY,
            title="Set Stage 3 revival cost",
            risk=ToolRisk.MEDIUM,
            description="Override revival INR estimate for repair-stage projects.",
            respects_factory_billing_hold=False,
        )
    )


_register_defaults()
