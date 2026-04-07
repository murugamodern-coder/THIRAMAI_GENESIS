"""Inventory domain manager — low stock → restock decisions (worker: inventory)."""

from __future__ import annotations

import os
from typing import Any

from core.agent_base import BaseAgent


class InventoryManager(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="inventory_manager", role="inventory_domain")

    def observe(self, context: dict[str, Any]) -> dict[str, Any]:
        state = context.get("_tenant_state") if isinstance(context.get("_tenant_state"), dict) else {}
        low = state.get("low_stock") if isinstance(state.get("low_stock"), dict) else {}
        return {
            "low_stock_count": int(low.get("count") or 0),
            "threshold": low.get("threshold"),
        }

    def decide(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        state = context.get("_tenant_state") if isinstance(context.get("_tenant_state"), dict) else {}
        low = state.get("low_stock") if isinstance(state.get("low_stock"), dict) else {}
        if not low.get("ok"):
            return []

        thr_raw = (os.getenv("THIRAMAI_DASHBOARD_LOW_STOCK_THRESHOLD") or "5").strip()
        try:
            thr = max(0, min(10_000, int(thr_raw)))
        except ValueError:
            thr = int(low.get("threshold") or 5)

        out: list[dict[str, Any]] = []
        for it in (low.get("items") or [])[:12]:
            if not isinstance(it, dict):
                continue
            sku = (it.get("sku_name") or "").strip()
            if not sku:
                continue
            cur = float(it.get("quantity") or 0)
            need = max(1.0, float(thr) - cur)
            out.append(
                {
                    "manager": self.name,
                    "worker": "inventory",
                    "intent": "add_inventory",
                    "entity": sku,
                    "quantity": need,
                    "reason": "low_stock_restock",
                    "priority": "high",
                    "reference": {
                        "current_qty": cur,
                        "threshold": thr,
                        "location": (it.get("location") or "").strip(),
                    },
                }
            )
        return out
