"""Growth domain manager — demand / sales opportunities (worker: research; suggestions only by default)."""

from __future__ import annotations

import os
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from core.agent_base import BaseAgent


def _money(s: Any) -> Decimal:
    try:
        return Decimal(str(s).replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


class GrowthManager(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="growth_manager", role="growth_domain")

    def observe(self, context: dict[str, Any]) -> dict[str, Any]:
        state = context.get("_tenant_state") if isinstance(context.get("_tenant_state"), dict) else {}
        dash = state.get("dashboard") if isinstance(state.get("dashboard"), dict) else {}
        rev_today = None
        if dash.get("ok"):
            rev = dash.get("revenue_inr") or {}
            rev_today = str(rev.get("today"))
        return {"revenue_today_inr": rev_today, "inventory_rows": int(state.get("inventory_row_count") or 0)}

    def decide(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        state = context.get("_tenant_state") if isinstance(context.get("_tenant_state"), dict) else {}
        dash = state.get("dashboard") if isinstance(state.get("dashboard"), dict) else {}
        if not dash.get("ok"):
            return []

        rev = dash.get("revenue_inr") or {}
        today = _money(rev.get("today"))
        month = _money(rev.get("this_month"))
        top = dash.get("top_selling_products") or []
        inv_rows = int(state.get("inventory_row_count") or 0)
        min_hour = int((os.getenv("THIRAMAI_AUTONOMOUS_NO_SALES_MIN_HOUR_UTC") or "12").strip() or "12")
        hour_utc = time.gmtime().tm_hour

        if today != 0 or inv_rows <= 0 or hour_utc < min_hour:
            return []
        if month <= 0 and len(top) == 0:
            return []

        return [
            {
                "manager": self.name,
                "worker": "research",
                "intent": "read_inventory",
                "decision_type": "no_sales_growth_review",
                "reason": "no_sales_today_suggest_campaign_or_channel_check",
                "priority": "medium",
                "entity": "",
                "quantity": None,
                "reference": {"min_hour_utc": min_hour},
            },
            {
                "manager": self.name,
                "worker": "research",
                "intent": None,
                "decision_type": "growth_suggestion",
                "reason": "review_merchandising_and_customer_outreach",
                "priority": "low",
                "reference": {},
            },
        ]
