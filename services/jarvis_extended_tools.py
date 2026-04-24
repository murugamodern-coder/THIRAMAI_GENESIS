"""Jarvis tools 10–25: business OS, research, market, lightweight creative drafts."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from groq import Groq
from sqlalchemy import func, or_, select

from core.database import get_session_factory
from core.db.models import Asset, Invoice, Payment, ProductionLog, StaffProfile, User
from services import business_os_service as bos
from services.billing_phase2_service import create_simple_cash_bill_sync, create_structured_invoice_sync
from services.business_depth_service import attendance_check_in, attendance_check_out, record_operational_expense
from services.inventory_phase2_service import (
    create_inventory_item_sync,
    list_inventory_items_sync,
    list_low_stock_alerts_sync,
    list_purchase_orders_sync,
    list_supplier_payments_sync,
    record_stock_movement_sync,
)

# re-import list_invoices
from services.billing_phase2_service import list_invoices_sync
from services.stock_market_jarvis import analyze_symbol_sync

_log = logging.getLogger("thiramai.jarvis_extended")

EXTENDED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "create_invoice",
        "add_stock",
        "record_sale",
        "add_business_expense",
        "get_business_pnl",
        "add_farmer",
        "update_subsidy_status",
        "log_production",
        "mark_attendance",
        "get_stock_status",
        "get_pending_payments",
        "research_topic",
        "research_market",
        "deep_research",
        "find_cheapest_machine",
        "find_govt_schemes",
        "generate_dpr",
        "analyze_competitors",
        "analyze_stock_opportunity",
        "get_stock_price",
        "analyze_stock",
        "generate_intraday_signal",
        "get_portfolio_summary",
        "add_to_watchlist",
        "generate_poster_content",
        "draft_business_email",
        "create_website",
        "match_unpaid_invoices",
        "apply_invoice_payment_match",
        "suggest_personal_expense_from_receipt",
    }
)

AUTO_EXECUTE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_today_brief",
        "get_business_snapshot",
        "search_inventory",
        "get_upcoming_emis",
        "get_business_pnl",
        "get_stock_status",
        "get_pending_payments",
        "research_topic",
        "research_market",
        "deep_research",
        "find_cheapest_machine",
        "find_govt_schemes",
        "generate_dpr",
        "analyze_competitors",
        "analyze_stock_opportunity",
        "get_stock_price",
        "analyze_stock",
        "generate_intraday_signal",
        "get_portfolio_summary",
        "add_to_watchlist",
        "generate_poster_content",
        "draft_business_email",
        "create_website",
        "suggest_personal_expense_from_receipt",
    }
)


def extended_tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "create_invoice",
                "description": "Create a GST tax invoice or a simple non-GST bill for a customer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "business_org_id": {"type": "integer"},
                        "customer_name": {"type": "string"},
                        "customer_phone": {"type": "string"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "qty": {"type": "number"},
                                    "rate": {"type": "number"},
                                    "hsn": {"type": "string"},
                                },
                            },
                        },
                        "is_gst": {"type": "boolean"},
                        "payment_mode": {"type": "string"},
                    },
                    "required": ["customer_name", "items", "is_gst"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_stock",
                "description": "Increase stock for an SKU (creates item if missing) with optional supplier note.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "org_id": {"type": "integer"},
                        "item_name": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit": {"type": "string"},
                        "cost_price": {"type": "number"},
                        "supplier_name": {"type": "string"},
                    },
                    "required": ["item_name", "quantity"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "record_sale",
                "description": "Record a quick retail sale (non-GST cash bill) and optionally deduct inventory by item name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "org_id": {"type": "integer"},
                        "amount": {"type": "number"},
                        "payment_mode": {"type": "string"},
                        "items_sold": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "qty": {"type": "number"},
                                    "rate": {"type": "number"},
                                },
                            },
                        },
                        "customer_name": {"type": "string"},
                    },
                    "required": ["amount"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_business_expense",
                "description": "Record operational expense for the business (P&L).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "org_id": {"type": "integer"},
                        "amount": {"type": "number"},
                        "category": {"type": "string"},
                        "description": {"type": "string"},
                        "paid_to": {"type": "string"},
                        "payment_mode": {"type": "string"},
                    },
                    "required": ["amount", "category"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_business_pnl",
                "description": "Read-only P&L for a period (today, week, month, custom).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "org_id": {"type": "integer"},
                        "period": {
                            "type": "string",
                            "enum": ["today", "week", "month", "custom"],
                        },
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                    },
                    "required": ["period"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_farmer",
                "description": "Add agro subsidy / farmer case.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "org_id": {"type": "integer"},
                        "name": {"type": "string"},
                        "village": {"type": "string"},
                        "taluk": {"type": "string"},
                        "phone": {"type": "string"},
                        "survey_number": {"type": "string"},
                        "land_acres": {"type": "number"},
                        "scheme_name": {"type": "string"},
                        "crop_type": {"type": "string"},
                    },
                    "required": ["name", "scheme_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_subsidy_status",
                "description": "Update subsidy case by farmer_id or farmer_name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "org_id": {"type": "integer"},
                        "farmer_id": {"type": "integer"},
                        "farmer_name": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["applied", "approved", "received", "rejected"],
                        },
                        "amount": {"type": "number"},
                        "notes": {"type": "string"},
                    },
                    "required": ["status"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "log_production",
                "description": "Log manufacturing output against a machine (asset) by name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "org_id": {"type": "integer"},
                        "machine_name": {"type": "string"},
                        "product_name": {"type": "string"},
                        "quantity_produced": {"type": "number"},
                        "unit": {"type": "string"},
                        "raw_material_used": {"type": "array", "items": {"type": "object"}},
                        "machine_hours": {"type": "number"},
                        "quality_pass": {"type": "boolean"},
                    },
                    "required": ["machine_name", "quantity_produced"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mark_attendance",
                "description": "Mark attendance for a worker linked to a user account (match username/email).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "org_id": {"type": "integer"},
                        "worker_name": {"type": "string"},
                        "date": {"type": "string"},
                        "status": {"type": "string", "enum": ["present", "absent", "half_day"]},
                        "in_time": {"type": "string"},
                        "out_time": {"type": "string"},
                    },
                    "required": ["worker_name", "status"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_stock_status",
                "description": "List inventory items, optional filter by item name.",
                "parameters": {
                    "type": "object",
                    "properties": {"org_id": {"type": "integer"}, "item_name": {"type": "string"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_pending_payments",
                "description": "Summarize receivables (unpaid invoices) and payable hints (open POs).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "org_id": {"type": "integer"},
                        "type": {"type": "string", "enum": ["receivable", "payable", "both"]},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "research_topic",
                "description": "Web research via Tavily + optional Groq summary.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "depth": {"type": "string", "enum": ["quick", "detailed"]},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "research_market",
                "description": "Structured India market intelligence (size, growth, players, trends) saved to research history.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "Product or industry e.g. groundnut oil"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "deep_research",
                "description": "Multi-source business intelligence (web, news, govt, marketplaces, optional social/academic). Saves to research_projects; returns summary, comparison table when relevant, and sources.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "depth": {
                            "type": "string",
                            "enum": ["quick", "standard", "deep"],
                            "description": "quick=web only; standard=web+news+govt; deep=all sources",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_cheapest_machine",
                "description": "Compare equipment/machine prices across IndiaMART, TradeIndia, and web snippets; returns comparison table and brief analysis.",
                "parameters": {
                    "type": "object",
                    "properties": {"machine_name": {"type": "string"}},
                    "required": ["machine_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_govt_schemes",
                "description": "Search current government schemes for TN/India sector (MSME, NABARD-style signals when business_type is set).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sector": {"type": "string"},
                        "state": {"type": "string"},
                        "business_type": {"type": "string", "description": "Optional e.g. food processing unit, dairy"},
                    },
                    "required": ["sector"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_dpr",
                "description": "Generate a DPR-style project report (executive summary, capex, ROI) as structured sections.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "business_type": {"type": "string"},
                        "capacity": {"type": "string"},
                        "location": {"type": "string"},
                    },
                    "required": ["business_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_competitors",
                "description": "Competitor landscape for a business type and location (web-backed).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "business_type": {"type": "string"},
                        "location": {"type": "string"},
                    },
                    "required": ["business_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_stock_price",
                "description": "Live last price for an NSE/BSE ticker (yfinance; short cache).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "exchange_suffix": {"type": "string", "description": "NS or BO"},
                    },
                    "required": ["symbol"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_stock",
                "description": "RSI, MACD, EMA9/21, Bollinger position, trend label for a symbol.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "interval": {"type": "string", "description": "e.g. 5m, 1d"},
                    },
                    "required": ["symbol"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_intraday_signal",
                "description": "Rule-based BUY/SELL/HOLD with levels (respects daily loss cap).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                    },
                    "required": ["symbol"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_portfolio_summary",
                "description": "User paper equity portfolio: value, per-line P&L, totals.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_to_watchlist",
                "description": "Add an NSE-style symbol to the user's market watchlist.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "exchange_suffix": {"type": "string"},
                    },
                    "required": ["symbol"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "match_unpaid_invoices",
                "description": "Find unpaid/partial invoices whose balance matches a bank credit amount (Upgrade 5).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "amount_inr": {"type": "number"},
                        "tolerance_inr": {"type": "number", "description": "Optional; default ~1 INR"},
                    },
                    "required": ["amount_inr"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "apply_invoice_payment_match",
                "description": "Record a payment against a specific invoice id (marks paid when balance cleared).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "invoice_id": {"type": "integer"},
                        "amount_inr": {"type": "number"},
                        "reference": {"type": "string"},
                    },
                    "required": ["invoice_id", "amount_inr"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "suggest_personal_expense_from_receipt",
                "description": "Build a short confirmation line for a detected personal expense (e.g. Swiggy food).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "vendor_name": {"type": "string"},
                        "amount_inr": {"type": "number"},
                        "category": {"type": "string"},
                    },
                    "required": ["vendor_name", "amount_inr"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_stock_opportunity",
                "description": "Technical view for an NSE symbol (not investment advice).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string", "enum": ["intraday", "swing"]},
                    },
                    "required": ["symbol"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_website",
                "description": "Build a static microsite from inventory + org profile; optional nginx deploy (THIRAMAI_WEB_DEPLOY_ENABLED).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "business_org_id": {
                            "type": "integer",
                            "description": "organizations.id (defaults to active org if omitted)",
                        },
                        "template_type": {
                            "type": "string",
                            "enum": ["shop", "manufacturing", "services"],
                            "description": "Visual/copy preset",
                        },
                        "deploy_now": {
                            "type": "boolean",
                            "description": "If true, also write nginx vhost + reload when enabled on server",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_poster_content",
                "description": "HTML poster shell + text for print/share.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "business_name": {"type": "string"},
                        "product_name": {"type": "string"},
                        "tagline": {"type": "string"},
                        "offer": {"type": "string"},
                        "contact": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "draft_business_email",
                "description": "Draft a professional email (Groq).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to_name": {"type": "string"},
                        "to_email": {"type": "string"},
                        "subject_type": {
                            "type": "string",
                            "enum": ["quotation", "follow_up", "payment_reminder", "introduction"],
                        },
                        "context_data": {"type": "string"},
                    },
                    "required": ["subject_type"],
                },
            },
        },
    ]


def _parse_date(s: str | None) -> date | None:
    if not (s or "").strip():
        return None
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except ValueError:
        return None


def _period_range(
    period: str, date_from: str | None, date_to: str | None
) -> tuple[date, date] | tuple[None, None]:
    today = datetime.now(timezone.utc).date()
    p = (period or "today").strip().lower()
    if p == "today":
        return today, today
    if p == "week":
        return today - timedelta(days=7), today
    if p == "month":
        return today.replace(day=1), today
    if p == "custom":
        a = _parse_date(date_from)
        b = _parse_date(date_to)
        if a and b and a <= b:
            return a, b
        return None, None
    return today, today


def _tavily_search(query: str, max_results: int = 5) -> dict[str, Any]:
    key = (os.getenv("TAVILY_API_KEY") or "").strip()
    if not key:
        return {"ok": False, "error": "TAVILY_API_KEY not set"}
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=key)
        return dict(client.search(query=query[:400], max_results=max_results))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _groq_summarize(text: str, *, max_words: int = 220) -> str:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key or not (text or "").strip():
        return (text or "")[:2000]
    model = (os.getenv("GROQ_SMART_MODEL") or os.getenv("GROQ_AGENT_MODEL") or "llama-3.3-70b-versatile").strip()
    try:
        client = Groq(api_key=key)
        chat = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": f"Summarize in English for an Indian business owner. Max {max_words} words. Bullet key facts.",
                },
                {"role": "user", "content": text[:12000]},
            ],
            temperature=0.2,
            max_tokens=512,
        )
        return (chat.choices[0].message.content or "").strip()
    except Exception:
        return text[:2000]


def execute_jarvis_extended_tool(
    *,
    name: str,
    args: dict[str, Any],
    user: Any,
    effective_org_id: int,
) -> dict[str, Any]:
    uid = int(user.id)
    oid = int(effective_org_id)
    if oid <= 0:
        return {"ok": False, "message": "invalid organization"}

    try:
        from services.product_plans import organization_plan_sync, plan_allows

        raw_plan = organization_plan_sync(oid)

        def _paywall(feature: str) -> dict[str, Any] | None:
            if not plan_allows(raw_plan, feature):
                return {
                    "ok": False,
                    "message": f"This capability requires Pro or Business ({feature}). See Pricing in the app.",
                    "paywall": True,
                    "feature": feature,
                    "plan": raw_plan,
                }
            return None

        if name in (
            "research_market",
            "deep_research",
            "find_cheapest_machine",
            "generate_dpr",
            "analyze_competitors",
            "research_topic",
            "find_govt_schemes",
        ):
            hit = _paywall("deep_research")
            if hit:
                return hit
        if name in ("suggest_personal_expense_from_receipt", "match_unpaid_invoices", "apply_invoice_payment_match"):
            hit = _paywall("auto_accounting")
            if hit:
                return hit

        if name == "create_invoice":
            cust = str(args.get("customer_name") or "").strip()
            phone = str(args.get("customer_phone") or "").strip()
            pay_mode = str(args.get("payment_mode") or "unknown").strip()
            items = args.get("items") or []
            is_gst = bool(args.get("is_gst", True))
            if not cust or not isinstance(items, list) or not items:
                return {"ok": False, "message": "customer_name and items required"}
            ext_ref = f"jarvis|{cust}|{phone}|pay:{pay_mode}"[:512]
            if is_gst:
                lines = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    nm = str(it.get("name") or "Item").strip()
                    qty = float(it.get("qty") or 0)
                    rate = float(it.get("rate") or 0)
                    if qty <= 0:
                        continue
                    lines.append(
                        {
                            "description": nm,
                            "quantity": qty,
                            "unit_price_pre_tax": rate,
                            "gst_rate_percent": 18.0,
                            "hsn_code": str(it.get("hsn") or "").strip() or None,
                        }
                    )
                if not lines:
                    return {"ok": False, "message": "no valid lines"}
                out = create_structured_invoice_sync(
                    organization_id=oid,
                    invoice_no="",
                    invoice_date=date.today(),
                    lines=lines,
                    external_ref=ext_ref,
                    user_id=uid if uid > 0 else None,
                )
                if not out.get("ok"):
                    return {"ok": False, "message": out.get("error") or "invoice failed"}
                return {
                    "ok": True,
                    "invoice_id": out.get("invoice_id"),
                    "invoice_number": out.get("invoice_no"),
                    "total_amount": out.get("grand_total_inr"),
                }
            lines2 = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                nm = str(it.get("name") or "Item").strip()
                qty = float(it.get("qty") or 1)
                rate = float(it.get("rate") or 0)
                lines2.append({"description": nm, "quantity": qty, "unit_price_inr": rate})
            out2 = create_simple_cash_bill_sync(
                organization_id=oid, lines=lines2, user_id=uid if uid > 0 else None
            )
            if not out2.get("ok"):
                return {"ok": False, "message": out2.get("error") or "bill failed"}
            return {
                "ok": True,
                "bill_id": out2.get("bill_id"),
                "invoice_number": f"BILL-{out2.get('bill_id')}",
                "total_amount": out2.get("total_amount_inr"),
            }

        if name == "add_stock":
            sku = str(args.get("item_name") or "").strip()
            qty = float(args.get("quantity") or 0)
            unit = str(args.get("unit") or "").strip()
            cost = args.get("cost_price")
            sup = str(args.get("supplier_name") or "").strip()
            if not sku or qty == 0:
                return {"ok": False, "message": "item_name and non-zero quantity required"}
            inv = list_inventory_items_sync(organization_id=oid)
            found_id: int | None = None
            if inv.get("ok") and isinstance(inv.get("items"), list):
                needle = sku.lower()
                for it in inv["items"]:
                    if str(it.get("sku_name") or "").lower() == needle:
                        found_id = int(it.get("id") or 0) or None
                        break
            note = f"Jarvis stock in; supplier: {sup}"[:500]
            if found_id:
                mov = record_stock_movement_sync(
                    organization_id=oid,
                    inventory_item_id=found_id,
                    quantity_delta=qty,
                    movement_type="IN",
                    reference_type="JARVIS",
                    notes=note,
                    reason="purchase",
                    user_id=uid if uid > 0 else None,
                )
                if not mov.get("ok"):
                    return {"ok": False, "message": mov.get("error") or "movement failed"}
                it = mov.get("item") or {}
                return {
                    "ok": True,
                    "item_id": found_id,
                    "new_quantity": it.get("quantity"),
                    "total_value": it.get("total_value"),
                }
            cr = create_inventory_item_sync(
                organization_id=oid,
                sku_name=sku,
                quantity=qty,
                unit=unit or None,
                unit_cost_pre_tax=float(cost) if cost is not None else None,
                user_id=uid if uid > 0 else None,
            )
            if not cr.get("ok"):
                return {"ok": False, "message": cr.get("error") or "create item failed"}
            it = (cr.get("item") or {})
            return {
                "ok": True,
                "item_id": it.get("id"),
                "new_quantity": it.get("quantity"),
                "total_value": it.get("total_value"),
            }

        if name == "record_sale":
            amt = float(args.get("amount") or 0)
            pay = str(args.get("payment_mode") or "cash").strip()
            cust = str(args.get("customer_name") or "Walk-in").strip()
            raw_items = args.get("items_sold") or []
            if amt <= 0 and not raw_items:
                return {"ok": False, "message": "amount or items_sold required"}
            lines = []
            if isinstance(raw_items, list) and raw_items:
                for it in raw_items:
                    if not isinstance(it, dict):
                        continue
                    lines.append(
                        {
                            "description": str(it.get("name") or "Item"),
                            "quantity": float(it.get("qty") or 1),
                            "unit_price_inr": float(it.get("rate") or 0),
                        }
                    )
            if not lines:
                lines = [{"description": f"Sale ({pay}) — {cust}", "quantity": 1, "unit_price_inr": amt}]
            out = create_simple_cash_bill_sync(
                organization_id=oid, lines=lines, user_id=uid if uid > 0 else None
            )
            if not out.get("ok"):
                return {"ok": False, "message": out.get("error") or "sale failed"}
            # optional stock OUT
            if isinstance(raw_items, list):
                inv = list_inventory_items_sync(organization_id=oid)
                items_map = {}
                if inv.get("ok"):
                    for it in inv.get("items") or []:
                        items_map[str(it.get("sku_name") or "").lower()] = int(it.get("id") or 0)
                for it in raw_items:
                    if not isinstance(it, dict):
                        continue
                    nm = str(it.get("name") or "").strip().lower()
                    q = float(it.get("qty") or 0)
                    iid = items_map.get(nm)
                    if iid and q > 0:
                        record_stock_movement_sync(
                            organization_id=oid,
                            inventory_item_id=iid,
                            quantity_delta=-q,
                            movement_type="OUT",
                            reference_type="JARVIS_SALE",
                            reference_id=str(out.get("bill_id")),
                            notes="Jarvis record_sale",
                            user_id=uid if uid > 0 else None,
                        )
            return {
                "ok": True,
                "sale_id": out.get("bill_id"),
                "profit_margin": None,
                "total_amount_inr": out.get("total_amount_inr"),
            }

        if name == "add_business_expense":
            amount = float(args.get("amount") or 0)
            cat = str(args.get("category") or "Other").strip()
            desc = str(args.get("description") or "").strip()
            paid_to = str(args.get("paid_to") or "").strip()
            pm = str(args.get("payment_mode") or "").strip()
            if amount <= 0:
                return {"ok": False, "message": "positive amount required"}
            full_desc = desc
            if paid_to:
                full_desc = f"{desc} | paid_to:{paid_to} | mode:{pm}".strip(" |")
            ok, msg, eid = record_operational_expense(
                organization_id=oid,
                expense_date=date.today(),
                category=cat[:64],
                amount_inr=amount,
                description=full_desc[:2000] if full_desc else None,
            )
            month_total = 0.0
            fac = get_session_factory()
            if fac is not None:
                with fac() as session:
                    from core.db.models import OperationalExpense

                    start_m = date.today().replace(day=1)
                    v = session.execute(
                        select(func.coalesce(func.sum(OperationalExpense.amount_inr), 0)).where(
                            OperationalExpense.organization_id == oid,
                            OperationalExpense.expense_date >= start_m,
                        )
                    ).scalar()
                    month_total = float(v or 0)
            return {"ok": ok, "message": msg, "expense_id": eid, "month_total_expenses": month_total}

        if name == "get_business_pnl":
            pr = str(args.get("period") or "today").strip().lower()
            start_d, end_d = _period_range(pr, args.get("date_from"), args.get("date_to"))
            if start_d is None:
                return {"ok": False, "message": "invalid custom period; pass date_from/date_to YYYY-MM-DD"}
            fac = get_session_factory()
            if fac is None:
                return {"ok": False, "message": "no database"}
            from core.db.models import Bill, OperationalExpense

            with fac() as session:
                start_dt = datetime(start_d.year, start_d.month, start_d.day, tzinfo=timezone.utc)
                end_dt = datetime(end_d.year, end_d.month, end_d.day, tzinfo=timezone.utc) + timedelta(days=1)
                bills = session.execute(
                    select(func.coalesce(func.sum(Bill.total_amount), 0)).where(
                        Bill.organization_id == oid,
                        Bill.created_at >= start_dt,
                        Bill.created_at < end_dt,
                    )
                ).scalar() or 0
                invs = session.execute(
                    select(func.coalesce(func.sum(Invoice.grand_total_inr), 0)).where(
                        Invoice.organization_id == oid,
                        Invoice.invoice_date.isnot(None),
                        Invoice.invoice_date >= start_d,
                        Invoice.invoice_date <= end_d,
                    )
                ).scalar() or 0
                opex = session.execute(
                    select(func.coalesce(func.sum(OperationalExpense.amount_inr), 0)).where(
                        OperationalExpense.organization_id == oid,
                        OperationalExpense.expense_date >= start_d,
                        OperationalExpense.expense_date <= end_d,
                    )
                ).scalar() or 0
                top_cat = session.execute(
                    select(OperationalExpense.category, func.sum(OperationalExpense.amount_inr))
                    .where(
                        OperationalExpense.organization_id == oid,
                        OperationalExpense.expense_date >= start_d,
                        OperationalExpense.expense_date <= end_d,
                    )
                    .group_by(OperationalExpense.category)
                    .order_by(func.sum(OperationalExpense.amount_inr).desc())
                    .limit(1)
                ).first()
            revenue = float(bills) + float(invs)
            expenses = float(opex)
            profit = revenue - expenses
            margin = round((profit / revenue * 100) if revenue > 0 else 0.0, 2)
            return {
                "ok": True,
                "period": pr,
                "revenue": round(revenue, 2),
                "expenses": round(expenses, 2),
                "profit": round(profit, 2),
                "profit_margin_percent": margin,
                "top_expense_category": (top_cat[0] if top_cat else None),
            }

        if name == "add_farmer":
            org_arg = int(args.get("org_id") or oid)
            if org_arg != oid:
                return {"ok": False, "message": "org mismatch"}
            notes_parts = []
            if args.get("taluk"):
                notes_parts.append(f"taluk: {args.get('taluk')}")
            if args.get("crop_type"):
                notes_parts.append(f"crop: {args.get('crop_type')}")
            notes = "; ".join(notes_parts) if notes_parts else None
            acres = args.get("land_acres")
            out = bos.create_subsidy_case_sync(
                organization_id=oid,
                farmer_name=str(args.get("name") or "").strip(),
                village=str(args.get("village") or "").strip(),
                survey_number=str(args.get("survey_number") or "").strip(),
                farmer_phone=str(args.get("phone") or "").strip() or None,
                land_acres=float(acres) if acres is not None else None,
                scheme_name=str(args.get("scheme_name") or "").strip(),
                application_status="draft",
                notes=notes,
            )
            if not out.get("ok"):
                return {"ok": False, "message": out.get("error") or "failed"}
            est = float(acres or 0) * 5000.0
            return {"ok": True, "farmer_id": out.get("id"), "subsidy_estimate_inr": round(est, 2)}

        if name == "update_subsidy_status":
            fid = int(args.get("farmer_id") or 0)
            fname = str(args.get("farmer_name") or "").strip()
            st = str(args.get("status") or "").strip().lower()
            amount = args.get("amount")
            notes = str(args.get("notes") or "").strip() or None
            if not st:
                return {"ok": False, "message": "status required"}
            case_id = fid
            if case_id <= 0 and fname:
                fac = get_session_factory()
                if fac is None:
                    return {"ok": False, "message": "no database"}
                from core.db.models import AgroSubsidyCase

                with fac() as session:
                    row = session.execute(
                        select(AgroSubsidyCase)
                        .where(
                            AgroSubsidyCase.organization_id == oid,
                            func.lower(AgroSubsidyCase.farmer_name).like(f"%{fname.lower()[:80]}%"),
                        )
                        .order_by(AgroSubsidyCase.id.desc())
                        .limit(1)
                    ).scalar_one_or_none()
                    case_id = int(row.id) if row else 0
            if case_id <= 0:
                return {"ok": False, "message": "farmer_id or farmer_name not found"}
            fields: dict[str, Any] = {"notes": notes}
            if st == "applied":
                fields["application_status"] = "applied"
                if amount is not None:
                    fields["subsidy_applied_inr"] = amount
            elif st == "approved":
                fields["application_status"] = "approved"
                if amount is not None:
                    fields["subsidy_approved_inr"] = amount
            elif st == "received":
                fields["application_status"] = "received"
                if amount is not None:
                    fields["subsidy_received_inr"] = amount
            elif st == "rejected":
                fields["application_status"] = "rejected"
            else:
                return {"ok": False, "message": "invalid status"}
            up = bos.update_subsidy_case_sync(organization_id=oid, case_id=case_id, **fields)
            if not up.get("ok"):
                return {"ok": False, "message": up.get("error") or "update failed"}
            return {"ok": True, "farmer_id": case_id, "status": st, "amount": amount}

        if name == "log_production":
            mname = str(args.get("machine_name") or "").strip()
            qty = float(args.get("quantity_produced") or 0)
            unit = str(args.get("unit") or "unit").strip() or "unit"
            if not mname or qty <= 0:
                return {"ok": False, "message": "machine_name and positive quantity_produced required"}
            fac = get_session_factory()
            if fac is None:
                return {"ok": False, "message": "no database"}
            pid = 0
            missing_asset: str | None = None
            with fac() as session:
                with session.begin():
                    asset = session.execute(
                        select(Asset)
                        .where(
                            Asset.organization_id == oid,
                            func.lower(Asset.name).like(f"%{mname.lower()[:60]}%"),
                        )
                        .limit(1)
                    ).scalar_one_or_none()
                    if asset is None:
                        missing_asset = mname
                    else:
                        qh = args.get("machine_hours")
                        qpass = args.get("quality_pass")
                        qstat = "pass" if qpass is True else "fail" if qpass is False else None
                        pl = ProductionLog(
                            asset_id=int(asset.id),
                            production_unit=unit[:64],
                            yield_out=Decimal(str(qty)),
                            machine_hours=Decimal(str(qh)) if qh is not None else None,
                            quality_status=qstat,
                            external_ref=str(args.get("product_name") or "")[:256] or None,
                        )
                        session.add(pl)
                        session.flush()
                        pid = int(pl.id)
            if missing_asset:
                return {"ok": False, "message": f"asset not found matching '{missing_asset}'"}
            cost_per_unit = None
            eff = None
            return {
                "ok": True,
                "production_id": pid,
                "cost_per_unit": cost_per_unit,
                "efficiency_percent": eff,
            }

        if name == "mark_attendance":
            wn = str(args.get("worker_name") or "").strip()
            st = str(args.get("status") or "present").strip().lower()
            if not wn:
                return {"ok": False, "message": "worker_name required"}
            fac = get_session_factory()
            if fac is None:
                return {"ok": False, "message": "no database"}
            with fac() as session:
                sp = session.execute(
                    select(StaffProfile)
                    .join(User, User.id == StaffProfile.user_id)
                    .where(
                        StaffProfile.organization_id == oid,
                        or_(
                            func.lower(User.username).like(f"%{wn.lower()}%"),
                            func.lower(User.email).like(f"%{wn.lower()}%"),
                        ),
                    )
                    .limit(1)
                ).scalar_one_or_none()
                if sp is None:
                    return {"ok": False, "message": f"no staff profile matching '{wn}'"}
                sid = int(sp.id)
                base_salary = float(sp.basic_salary or 0)
            day_s = str(args.get("date") or "")[:10]
            try:
                d = date.fromisoformat(day_s) if day_s else datetime.now(timezone.utc).date()
            except ValueError:
                d = datetime.now(timezone.utc).date()
            in_s = str(args.get("in_time") or "").strip()
            out_s = str(args.get("out_time") or "").strip()
            check_in = datetime(d.year, d.month, d.day, 9, 0, tzinfo=timezone.utc)
            if in_s and ":" in in_s:
                parts = in_s.replace(".", ":").split(":")
                try:
                    h, m = int(parts[0]), int(parts[1])
                    check_in = datetime(d.year, d.month, d.day, h, m, tzinfo=timezone.utc)
                except Exception:
                    pass
            st_norm = "present" if st == "present" else "absent" if st == "absent" else "half_day"
            ok, msg, lid = attendance_check_in(
                organization_id=oid, staff_profile_id=sid, check_in=check_in, status=st_norm
            )
            if not ok or not lid:
                return {"ok": False, "message": msg}
            if out_s and ":" in out_s:
                parts = out_s.replace(".", ":").split(":")
                try:
                    h, m = int(parts[0]), int(parts[1])
                    co = datetime(d.year, d.month, d.day, h, m, tzinfo=timezone.utc)
                    attendance_check_out(organization_id=oid, attendance_log_id=int(lid), check_out=co)
                except Exception:
                    pass
            daily_wage = base_salary / 26.0 if st_norm == "present" else 0.0
            return {"ok": True, "worker_name": wn, "status": st_norm, "wage_for_day_inr": round(daily_wage, 2)}

        if name == "get_stock_status":
            inv = list_inventory_items_sync(organization_id=oid)
            low = list_low_stock_alerts_sync(organization_id=oid, threshold_override=5.0)
            items = inv.get("items") if inv.get("ok") else []
            needle = str(args.get("item_name") or "").strip().lower()
            if needle:
                items = [x for x in items if needle in str(x.get("sku_name") or "").lower()]
            total_val = sum(float(x.get("total_value") or 0) for x in items if isinstance(x, dict))
            return {
                "ok": True,
                "items": items[:80],
                "low_stock_alerts": low.get("alerts") if isinstance(low, dict) else [],
                "total_inventory_value": round(total_val, 2),
            }

        if name == "get_pending_payments":
            mode = str(args.get("type") or "both").strip().lower()
            out: dict[str, Any] = {"ok": True}
            if mode in ("receivable", "both"):
                li = list_invoices_sync(organization_id=oid, limit=200)
                invs = [x for x in (li.get("invoices") or []) if x.get("payment_status") != "paid"]
                total_rec = 0.0
                overdue: list[dict[str, Any]] = []
                today = datetime.now(timezone.utc).date()
                for inv in invs:
                    due_amt = float(inv.get("grand_total_inr") or 0)
                    pays = inv.get("payments") or []
                    paid = sum(float(p.get("amount_inr") or 0) for p in pays if isinstance(p, dict))
                    due = max(0.0, due_amt - paid)
                    if due <= 0.01:
                        continue
                    total_rec += due
                    idate = inv.get("invoice_date")
                    od_days = 0
                    if idate:
                        try:
                            idd = date.fromisoformat(str(idate)[:10])
                            od_days = (today - idd).days
                        except ValueError:
                            pass
                    entry = {
                        "invoice_id": inv.get("id"),
                        "invoice_no": inv.get("invoice_no"),
                        "amount_due": round(due, 2),
                        "overdue_days": od_days,
                    }
                    if od_days >= 30:
                        overdue.append(entry)
                out["total_receivable"] = round(total_rec, 2)
                out["overdue_list"] = overdue[:25]
                out["upcoming_list"] = []
            if mode in ("payable", "both"):
                po = list_purchase_orders_sync(organization_id=oid, limit=80)
                pay_total = 0.0
                rows = []
                for p in po.get("purchase_orders") or []:
                    if str(p.get("status") or "").lower() in ("received", "cancelled"):
                        continue
                    t = float(p.get("total_inr") or 0)
                    pay_total += t
                    rows.append({"po_id": p.get("id"), "status": p.get("status"), "open_commitment_inr": t})
                spay = list_supplier_payments_sync(organization_id=oid, limit=30)
                out["total_payable_hint"] = round(pay_total, 2)
                out["open_purchase_orders"] = rows[:20]
                out["recent_supplier_payments"] = (spay.get("payments") or [])[:10]
            return out

        if name == "research_market":
            from services.research_market_service import research_market_sync

            q = str(args.get("query") or "").strip()
            if not q:
                return {"ok": False, "message": "query required"}
            return research_market_sync(q, user_id=uid, organization_id=oid, persist=True)

        if name == "deep_research":
            from services.deep_research_engine import deep_research_sync

            q = str(args.get("query") or "").strip()
            dep = str(args.get("depth") or "standard").strip().lower()
            if not q:
                return {"ok": False, "message": "query required"}
            return deep_research_sync(
                q,
                dep,
                user_id=uid if uid > 0 else None,
                organization_id=oid if oid > 0 else None,
                persist=True,
            )

        if name == "find_cheapest_machine":
            from services.deep_research_engine import find_cheapest_machine_sync

            m = str(args.get("machine_name") or "").strip()
            if not m:
                return {"ok": False, "message": "machine_name required"}
            return find_cheapest_machine_sync(
                m,
                user_id=uid if uid > 0 else None,
                organization_id=oid if oid > 0 else None,
            )

        if name == "generate_dpr":
            from services.dpr_generator_service import generate_dpr_sync

            bt = str(args.get("business_type") or "").strip()
            cap = str(args.get("capacity") or "").strip()
            loc = str(args.get("location") or "").strip()
            if not bt:
                return {"ok": False, "message": "business_type required"}
            out = generate_dpr_sync(
                bt, cap, loc, user_id=uid, organization_id=oid, persist=True
            )
            slim = {k: v for k, v in out.items() if k not in ("pdf_base64", "html")}
            slim["pdf_note"] = "PDF/HTML generated — open Research → DPR or GET /research/dpr to download."
            return slim

        if name == "analyze_competitors":
            from services.research_competitor_service import analyze_competitors_sync

            bt = str(args.get("business_type") or "").strip()
            loc = str(args.get("location") or "").strip()
            if not bt:
                return {"ok": False, "message": "business_type required"}
            return analyze_competitors_sync(
                bt, loc, user_id=uid, organization_id=oid, persist=True
            )

        if name == "research_topic":
            q = str(args.get("query") or "").strip()
            depth = str(args.get("depth") or "quick").strip().lower()
            if not q:
                return {"ok": False, "message": "query required"}
            raw = _tavily_search(q, max_results=6)
            if isinstance(raw, dict) and raw.get("ok") is False:
                return {"ok": False, "message": raw.get("error") or "tavily failed"}
            results = raw.get("results") if isinstance(raw, dict) else []
            urls = []
            blob = []
            for r in results[:6]:
                if not isinstance(r, dict):
                    continue
                blob.append(f"{r.get('title')}: {r.get('content') or r.get('snippet') or ''}")
                if r.get("url"):
                    urls.append(str(r.get("url")))
            joined = "\n".join(blob)[:8000]
            summary = _groq_summarize(joined, max_words=220 if depth == "detailed" else 120)
            bullets = [ln.strip("- ").strip() for ln in summary.split("\n") if ln.strip().startswith("-")][:5]
            if len(bullets) < 3:
                bullets = [s.strip() for s in summary.split(". ")[:5] if s.strip()]
            out = {
                "ok": True,
                "summary": summary[:2500],
                "key_points": bullets[:5],
                "sources": urls[:3],
            }
            if depth == "detailed" and uid > 0:
                try:
                    from core.db.models import ResearchProject

                    fac = get_session_factory()
                    if fac is not None:
                        with fac() as session:
                            with session.begin():
                                org_id = int(oid) if oid and int(oid) > 0 else 1
                                rp = ResearchProject(
                                    user_id=uid,
                                    organization_id=org_id,
                                    title=q[:200][:300],
                                    domain="personal",
                                    status="active",
                                    folders_json={},
                                    sources_json={"sources": urls[:10], "kind": "jarvis_research"},
                                    notes_json={"description": summary[:4000]},
                                    summaries_json={},
                                    experiments_json={},
                                    outputs_json={},
                                )
                                session.add(rp)
                except Exception:
                    pass
            return out

        if name == "find_govt_schemes":
            sector = str(args.get("sector") or "").strip()
            state = str(args.get("state") or "Tamil Nadu").strip()
            bt = str(args.get("business_type") or "").strip()
            if bt:
                from services.deep_research_engine import find_govt_schemes_deep_sync

                return find_govt_schemes_deep_sync(
                    sector,
                    state,
                    bt,
                    user_id=uid,
                    organization_id=oid,
                )
            from services.research_schemes_service import find_schemes_sync

            return find_schemes_sync(
                sector,
                state,
                user_id=uid,
                organization_id=oid,
                persist=True,
                match_alerts=True,
            )

        if name == "analyze_stock_opportunity":
            sym = str(args.get("symbol") or "").strip().upper()
            tf = str(args.get("timeframe") or "intraday").strip().lower()
            if not sym:
                return {"ok": False, "message": "symbol required"}
            return analyze_symbol_sync(symbol=sym, timeframe=tf)

        if name == "get_stock_price":
            sym = str(args.get("symbol") or "").strip().upper()
            ex = str(args.get("exchange_suffix") or "NS").strip().upper() or "NS"
            if not sym:
                return {"ok": False, "message": "symbol required"}
            from services.stock_market_data_service import get_live_price

            return get_live_price(sym, exchange_suffix=ex)

        if name == "analyze_stock":
            sym = str(args.get("symbol") or "").strip().upper()
            iv = str(args.get("interval") or "5m").strip().lower()
            if not sym:
                return {"ok": False, "message": "symbol required"}
            from services.stock_indicator_service import analyze_indicators

            return analyze_indicators(sym, interval=iv or "5m", exchange_suffix="NS")

        if name == "generate_intraday_signal":
            sym = str(args.get("symbol") or "").strip().upper()
            if not sym:
                return {"ok": False, "message": "symbol required"}
            from services.stock_signal_service import generate_intraday_signal

            return generate_intraday_signal(sym, user_id=uid if uid > 0 else None, exchange_suffix="NS")

        if name == "get_portfolio_summary":
            from services.portfolio_service import get_portfolio_summary_sync

            if uid <= 0:
                return {"ok": False, "message": "user id required"}
            return get_portfolio_summary_sync(uid)

        if name == "add_to_watchlist":
            sym = str(args.get("symbol") or "").strip().upper()
            ex = str(args.get("exchange_suffix") or "NS").strip().upper() or "NS"
            if not sym:
                return {"ok": False, "message": "symbol required"}
            from services.portfolio_service import add_to_watchlist_sync

            if uid <= 0:
                return {"ok": False, "message": "user id required"}
            return add_to_watchlist_sync(uid, sym, exchange_suffix=ex)

        if name == "match_unpaid_invoices":
            from decimal import Decimal

            from services.auto_accounting_service import match_unpaid_invoices_sync

            raw = args.get("amount_inr")
            if raw is None:
                return {"ok": False, "message": "amount_inr required"}
            tol = args.get("tolerance_inr")
            try:
                tdec = Decimal(str(tol)) if tol is not None else Decimal("1.00")
            except Exception:
                tdec = Decimal("1.00")
            return match_unpaid_invoices_sync(
                organization_id=oid,
                amount_inr=Decimal(str(raw)),
                tolerance_inr=tdec,
            )

        if name == "apply_invoice_payment_match":
            from decimal import Decimal

            from services.auto_accounting_service import apply_invoice_payment_match_sync

            try:
                iid = int(args.get("invoice_id") or 0)
            except (TypeError, ValueError):
                iid = 0
            raw_amt = args.get("amount_inr")
            if iid <= 0 or raw_amt is None:
                return {"ok": False, "message": "invoice_id and amount_inr required"}
            ref = str(args.get("reference") or "").strip() or None
            return apply_invoice_payment_match_sync(
                organization_id=oid,
                invoice_id=iid,
                amount_inr=Decimal(str(raw_amt)),
                reference=ref,
                user_id=uid if uid > 0 else None,
            )

        if name == "suggest_personal_expense_from_receipt":
            from services.auto_accounting_service import jarvis_expense_detection_message

            scan = {
                "ok": True,
                "amount": float(args.get("amount_inr") or 0),
                "vendor_name": str(args.get("vendor_name") or "").strip(),
                "category": str(args.get("category") or "other").strip(),
            }
            if not scan["vendor_name"] or not scan["amount"]:
                return {"ok": False, "message": "vendor_name and amount_inr required"}
            return {
                "ok": True,
                "message": jarvis_expense_detection_message(scan),
                "hint": "User can confirm in Personal Finance → receipt scan.",
            }

        if name == "create_website":
            from services.website_builder_service import build_website_sync, user_can_access_org_sync

            raw_oid = args.get("business_org_id")
            if raw_oid is None or str(raw_oid).strip() == "":
                site_org_id = int(effective_org_id)
            else:
                try:
                    site_org_id = int(raw_oid)
                except (TypeError, ValueError):
                    return {"ok": False, "message": "invalid business_org_id"}
            if site_org_id <= 0:
                return {"ok": False, "message": "business_org_id required"}
            if int(site_org_id) != int(effective_org_id) and not user_can_access_org_sync(
                user_id=uid, organization_id=int(site_org_id)
            ):
                return {"ok": False, "message": "forbidden for this organization"}
            tt = str(args.get("template_type") or "shop").strip().lower()
            deploy = bool(args.get("deploy_now", False))
            if uid <= 0:
                return {"ok": False, "message": "user id required"}
            out = build_website_sync(int(site_org_id), tt, user_id=uid, run_deploy=deploy)
            if not out.get("ok"):
                return {"ok": False, "message": out.get("error") or "build failed"}
            return {
                "ok": True,
                "message": f"Site built. Public URL (needs wildcard DNS): {out.get('public_url')}",
                **out,
            }

        if name == "generate_poster_content":
            bn = str(args.get("business_name") or "Our Business").strip()
            pn = str(args.get("product_name") or "").strip()
            tag = str(args.get("tagline") or "").strip()
            off = str(args.get("offer") or "").strip()
            ct = str(args.get("contact") or "").strip()
            text = f"{bn}\n{pn}\n{tag}\n{off}\n{ct}".strip()
            html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Poster</title>
<style>
body{{margin:0;font-family:system-ui;background:#111;color:#fff;display:flex;min-height:100vh;align-items:center;justify-content:center;}}
.card{{max-width:520px;padding:32px;border:4px solid #f59e0b;text-align:center;background:#1f2937;}}
h1{{font-size:1.8rem;margin:0 0 12px;}}
p{{margin:8px 0;opacity:0.95;}}
.offer{{font-size:1.4rem;color:#fbbf24;margin-top:16px;font-weight:700;}}
</style></head><body><div class="card">
<h1>{bn}</h1>
<p>{pn}</p>
<p><em>{tag}</em></p>
<div class="offer">{off}</div>
<p style="margin-top:20px;font-size:1.1rem;">{ct}</p>
</div></body></html>"""
            return {"ok": True, "poster_html": html, "poster_text_content": text}

        if name == "draft_business_email":
            st = str(args.get("subject_type") or "follow_up").strip().lower()
            ctx = str(args.get("context_data") or "").strip()
            to_name = str(args.get("to_name") or "Sir/Madam").strip()
            key = (os.getenv("GROQ_API_KEY") or "").strip()
            if not key:
                return {"ok": False, "message": "GROQ_API_KEY not set"}
            model = (os.getenv("GROQ_FAST_MODEL") or "llama-3.1-8b-instant").strip()
            prompt = f"Write a short professional email ({st}) to {to_name}. Context: {ctx[:2000]}"
            client = Groq(api_key=key)
            chat = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You write concise business emails. Indian English."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.35,
                max_tokens=600,
            )
            body = (chat.choices[0].message.content or "").strip()
            subj = f"{st.replace('_', ' ').title()} — {to_name}"
            return {"ok": True, "subject": subj[:200], "email_body": body}

        return {"ok": False, "message": f"unknown extended tool {name}"}
    except Exception as exc:
        _log.exception("extended tool %s", name)
        return {"ok": False, "message": str(exc) or "tool error"}
