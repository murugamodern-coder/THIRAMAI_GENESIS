"""Routine ops short-circuit: command center, sales snapshot, POS sell — no Groq/Tavily/council."""

from __future__ import annotations

import os

import vault_memory
from core.brain_output import ActionIntentNone, BrainStructuredResponse, SellStockAction
from core.retail_sale_auth import role_may_execute_retail_sale
from core.router import query_is_personal_vault_priority, route_is_industrial_business
from core.sale_intent_heuristic import parsed_sell_intent_from_message
from services.analytics_service import (
    compute_dashboard_summary_sync,
    list_low_stock_alerts_sync,
    user_requests_sales_analytics,
)
from services.command_center import (
    build_unified_snapshot,
    format_command_center_oneline,
    user_requests_command_center,
)
from fastapi import HTTPException

from api.dependencies import ROLE_LEVEL_BY_NAME
from services.sale_execution import execute_sell_stock_sync


def routine_brief_enabled() -> bool:
    v = (os.getenv("THIRAMAI_ROUTINE_BRIEF") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _low_stock_threshold() -> int:
    thr_raw = (os.getenv("THIRAMAI_DASHBOARD_LOW_STOCK_THRESHOLD") or "5").strip()
    try:
        return max(0, min(10_000, int(thr_raw)))
    except ValueError:
        return 5


def try_routine_brief_only(
    raw: str,
    organization_id: int,
    *,
    actor_role_name: str | None,
    user_id: int | None = None,
    correlation_id: str | None = None,
) -> BrainStructuredResponse | None:
    if not routine_brief_enabled():
        return None
    if query_is_personal_vault_priority(raw):
        return None
    if route_is_industrial_business(raw):
        return None

    cmd = user_requests_command_center(raw)
    sales = user_requests_sales_analytics(raw)
    sell = parsed_sell_intent_from_message(raw)
    thr = _low_stock_threshold()

    if vault_memory.business_current_loaded():
        if not (cmd or sales or (sell is not None and len(raw.strip()) <= 240)):
            return None

    if cmd:
        snap = build_unified_snapshot(int(organization_id), low_stock_threshold=thr)
        line = format_command_center_oneline(snap)
        return BrainStructuredResponse(
            narrative=f"**Action Completed:** Command center · {line}",
            action_intent=ActionIntentNone(),
        )

    if sales and len(raw) <= 500:
        summary = compute_dashboard_summary_sync(
            int(organization_id), low_stock_threshold=thr
        )
        if not summary.get("ok"):
            err = summary.get("error") or "unavailable"
            return BrainStructuredResponse(
                narrative=f"**Action Completed:** Sales snapshot unavailable ({err}).",
                action_intent=ActionIntentNone(),
            )
        rev = summary["revenue_inr"]
        alerts = list_low_stock_alerts_sync(int(organization_id), threshold=thr)
        low_n = int(alerts.get("count") or 0) if alerts.get("ok") else 0
        return BrainStructuredResponse(
            narrative=(
                "**Action Completed:** Sales · Today ₹"
                + str(rev["today"])
                + " · Week ₹"
                + str(rev["this_week"])
                + " · Month ₹"
                + str(rev["this_month"])
                + f" · Low-stock SKUs: {low_n}."
            ),
            action_intent=ActionIntentNone(),
        )

    if sell is not None and len(raw.strip()) <= 240:
        return _routine_execute_sell(
            sell,
            int(organization_id),
            actor_role_name=actor_role_name,
            user_id=user_id,
            correlation_id=correlation_id,
            user_message=raw,
        )

    return None


def _routine_execute_sell(
    intent: SellStockAction,
    organization_id: int,
    *,
    actor_role_name: str | None,
    user_id: int | None = None,
    correlation_id: str | None = None,
    user_message: str = "",
) -> BrainStructuredResponse:
    flag = (os.getenv("THIRAMAI_AUTO_EXECUTE_SELL_STOCK") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return BrainStructuredResponse(
            narrative=(
                "**Action Completed:** Sell intent recorded (auto-execution off). "
                "Use HITL or set `THIRAMAI_AUTO_EXECUTE_SELL_STOCK=1`."
            ),
            action_intent=intent,
        )
    if not role_may_execute_retail_sale(actor_role_name):
        return BrainStructuredResponse(
            narrative=(
                "**Action Completed:** Sale not executed — retail posting requires **admin** or **staff**."
            ),
            action_intent=ActionIntentNone(),
        )
    igst = (os.getenv("THIRAMAI_RETAIL_GST_IGST") or "").strip().lower() in ("1", "true", "yes", "on")
    uid = int(user_id) if user_id is not None and int(user_id) > 0 else None
    role_level = (
        ROLE_LEVEL_BY_NAME.get((actor_role_name or "customer").lower(), 5)
        if uid is not None
        else None
    )
    try:
        result = execute_sell_stock_sync(
            organization_id=int(organization_id),
            sku_name=intent.sku_name,
            quantity=float(intent.quantity),
            location=intent.location or "",
            interstate_gst=igst,
            principal_user_id=uid,
            principal_role_level=role_level,
            correlation_id=correlation_id,
        )
    except HTTPException:
        raise
    try:
        from services.ltm_hooks import record_inventory_sell_execution

        record_inventory_sell_execution(
            organization_id=int(organization_id),
            prompt_context=user_message or "",
            sku_name=intent.sku_name,
            quantity=float(intent.quantity),
            location=intent.location or "",
            result=result,
            correlation_id=correlation_id,
        )
    except Exception:
        pass
    if result.get("policy") == "PROPOSE":
        detail = result.get("detail") or "Supervisor or owner confirmation required before posting this sale."
        return BrainStructuredResponse(
            narrative=(
                "**Pending approval (policy engine):** "
                + str(detail)
                + " Use owner/manager approval or HITL before posting."
            ),
            action_intent=ActionIntentNone(),
        )
    if not result.get("ok"):
        return BrainStructuredResponse(
            narrative=f"**Action Completed:** Sale not executed — {result.get('error', 'unknown error')}.",
            action_intent=ActionIntentNone(),
        )
    msg = (
        f"**Action Completed:** Bill **#{result['bill_id']}** · ₹{result['total_amount']:.2f} · "
        f"`{result['sku_name']}` × **{result['quantity_sold']}** · remaining **{result['remaining_quantity']:.4f}**."
    )
    return BrainStructuredResponse(narrative=msg, action_intent=ActionIntentNone())
