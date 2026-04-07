"""Compliance domain manager — GST / statutory signals (worker: notification; optional safe read)."""

from __future__ import annotations

from typing import Any

from core.agent_base import BaseAgent


class ComplianceManager(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="compliance_manager", role="compliance_domain")

    def observe(self, context: dict[str, Any]) -> dict[str, Any]:
        state = context.get("_tenant_state") if isinstance(context.get("_tenant_state"), dict) else {}
        notes = state.get("notifications") if isinstance(state.get("notifications"), dict) else {}
        gstish = 0
        for item in notes.get("items") or []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").lower()
            blob = f"{item.get('title') or ''} {item.get('body') or ''}".lower()
            if "gst" in kind or "gst" in blob:
                gstish += 1
        return {"gst_related_notifications": gstish}

    def decide(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        state = context.get("_tenant_state") if isinstance(context.get("_tenant_state"), dict) else {}
        notes = state.get("notifications") if isinstance(state.get("notifications"), dict) else {}
        out: list[dict[str, Any]] = []

        for item in notes.get("items") or []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "")
            blob = f"{item.get('title') or ''} {item.get('body') or ''}".lower()
            if "gst" not in kind.lower() and "gst" not in blob:
                continue
            out.append(
                {
                    "manager": self.name,
                    "worker": "notification",
                    "intent": None,
                    "decision_type": "gst_compliance_review",
                    "reason": "gst_pending_or_notification_requires_review",
                    "priority": "high",
                    "reference": {
                        "notification_id": item.get("id"),
                        "kind": kind,
                    },
                }
            )
            out.append(
                {
                    "manager": self.name,
                    "worker": "research",
                    "intent": "read_inventory",
                    "decision_type": "gst_context_snapshot",
                    "reason": "refresh_inventory_tax_fields_for_compliance_check",
                    "priority": "medium",
                    "entity": "",
                    "quantity": None,
                    "reference": {},
                }
            )
            break

        return out[:12]
