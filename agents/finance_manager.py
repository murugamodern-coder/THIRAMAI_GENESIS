"""Finance domain manager — alerts and cashflow hints (worker: notification only; no sells)."""

from __future__ import annotations

from typing import Any

from core.agent_base import BaseAgent


class FinanceManager(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="finance_manager", role="finance_domain")

    def observe(self, context: dict[str, Any]) -> dict[str, Any]:
        state = context.get("_tenant_state") if isinstance(context.get("_tenant_state"), dict) else {}
        notes = state.get("notifications") if isinstance(state.get("notifications"), dict) else {}
        items = [x for x in (notes.get("items") or []) if isinstance(x, dict)]
        debt_n = sum(1 for x in items if str(x.get("kind") or "") == "debt_overdue")
        return {"debt_overdue_notifications": debt_n, "unread_total": len(items)}

    def decide(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        state = context.get("_tenant_state") if isinstance(context.get("_tenant_state"), dict) else {}
        notes = state.get("notifications") if isinstance(state.get("notifications"), dict) else {}
        out: list[dict[str, Any]] = []

        for item in notes.get("items") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("kind") or "") != "debt_overdue":
                continue
            out.append(
                {
                    "manager": self.name,
                    "worker": "notification",
                    "intent": None,
                    "decision_type": "debt_overdue_review",
                    "reason": "overdue_debt_requires_operator_follow_up",
                    "priority": "high",
                    "reference": {
                        "notification_id": item.get("id"),
                        "kind": item.get("kind"),
                        "title": item.get("title"),
                    },
                }
            )

        dash = state.get("dashboard") if isinstance(state.get("dashboard"), dict) else {}
        if dash.get("ok"):
            rev = dash.get("revenue_inr") or {}
            today = str(rev.get("today") or "0").replace(",", "")
            try:
                tval = float(today or "0")
            except ValueError:
                tval = 0.0
            if tval == 0 and int(state.get("inventory_row_count") or 0) > 0:
                out.append(
                    {
                        "manager": self.name,
                        "worker": "notification",
                        "intent": None,
                        "decision_type": "revenue_watch",
                        "reason": "zero_revenue_today_with_stock_on_hand_review_pos",
                        "priority": "medium",
                        "reference": {},
                    }
                )

        return out[:20]
