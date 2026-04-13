"""
Groq tool-calling agent for THIRAMAI actions (missions, expenses, meetings, brief, etc.).

Flow:
- Queries are routed to a **tool subset** + fast/smart model (see ``jarvis_router``).
- Multi-step **read-only** tool loop (``THIRAMAI_JARVIS_MAX_STEPS``) with proper tool messages for Groq.
- Mutating tools: ``needs_confirmation`` + ``agent_pending_id``; batch confirm **or** per-card
  ``agent_confirm_tool_index`` / ``agent_reject_tool_index``.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from groq import Groq
from sqlalchemy import func, select
from core.database import get_session_factory
from core.db.models import Inventory, InventoryItem, PersonalLoan, PersonalMeeting, UserOrganizationMembership
from core.jarvis_pending_redis import (
    pending_delete,
    pending_peek,
    pending_pop,
    pending_set,
    undo_pop_stack,
    undo_store,
)
from services import life_os_service
from services import personal_command_center_service as pcc
from services.analytics_service import compute_dashboard_summary_sync
from services.jarvis_extended_tools import (
    AUTO_EXECUTE_TOOL_NAMES,
    EXTENDED_TOOL_NAMES,
    execute_jarvis_extended_tool,
    extended_tool_specs,
)
from services.jarvis_memory_learn import learn_from_turn_sync
from services.jarvis_memory_service import bump_memory_usage_sync, fetch_memory_entries_sync
from services.jarvis_router import merge_route_tool_specs
from services.inventory_phase2_service import list_low_stock_alerts_sync
from services.jarvis_undo_service import meeting_undo_payload
from services.personal_meetings_service import MEETING_TYPES, create_meeting, normalize_attendees

_log = logging.getLogger("thiramai.jarvis_agent")

_PENDING_TTL_SEC = 600
_IST = ZoneInfo("Asia/Kolkata")

TAMIL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "stock": ("stock", "சரக்கு", "பொருள்"),
    "sale": ("sale", "விற்பனை"),
    "expense": ("expense", "செலவு"),
    "farmer": ("farmer", "விவசாயி"),
    "meeting": ("meeting", "சந்திப்பு"),
    "invoice": ("invoice", "bill", "பில்"),
}


def _looks_tamil(text: str) -> bool:
    return any("\u0b80" <= c <= "\u0bff" for c in (text or ""))


BASE_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a personal mission / task with optional priority and due date (ISO 8601).",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "priority": {"type": "string", "enum": ["P1", "P2", "P3"], "description": "Default P2"},
                    "due_date": {"type": "string", "description": "ISO datetime optional"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_expense",
            "description": "Log a personal expense in INR.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "category": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["amount", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_meeting",
            "description": "Schedule a meeting. datetime is ISO 8601; if no timezone, it is interpreted as Asia/Kolkata (IST).",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "meeting_type": {"type": "string", "description": "e.g. client, business, personal"},
                    "datetime": {"type": "string"},
                    "duration_minutes": {"type": "integer", "default": 60},
                    "attendees": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["title", "meeting_type", "datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_today_brief",
            "description": "Fetch unified Today hero payload (focus task, meetings, alerts, business snapshot).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_business_snapshot",
            "description": "Revenue summary for the user's organization.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_health_log",
            "description": "Log today's health metrics (sleep hours, water glasses, stress 1-10).",
            "parameters": {
                "type": "object",
                "properties": {
                    "sleep": {"type": "number"},
                    "water": {"type": "integer"},
                    "stress": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_inventory",
            "description": "Search SKU names by substring for the active organization.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_upcoming_emis",
            "description": "List upcoming personal loan EMIs.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_habit",
            "description": "Create a daily (or custom frequency) habit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "category": {"type": "string"},
                    "goal_frequency": {"type": "string", "default": "daily"},
                },
                "required": ["title"],
            },
        },
    },
]

TOOL_SPECS: list[dict[str, Any]] = BASE_TOOL_SPECS + extended_tool_specs()


def resolve_jarvis_organization_id(user: Any, requested: int | None) -> tuple[int, str | None]:
    """Active JWT org, or another org the user belongs to."""
    jwt_org = int(user.organization_id)
    if requested is None or int(requested) <= 0:
        return jwt_org, None
    rid = int(requested)
    if rid == jwt_org:
        return jwt_org, None
    factory = get_session_factory()
    if factory is None:
        return jwt_org, "database unavailable"
    with factory() as session:
        m = session.execute(
            select(UserOrganizationMembership.id).where(
                UserOrganizationMembership.user_id == int(user.id),
                UserOrganizationMembership.organization_id == rid,
                UserOrganizationMembership.is_active.is_(True),
            ).limit(1)
        ).scalar_one_or_none()
    if m is None:
        return jwt_org, "Select an organization you belong to, or switch workspace first."
    return rid, None


def _route_groq_model(message: str) -> str:
    q = (message or "").lower()
    fast = (os.getenv("GROQ_FAST_MODEL") or "llama-3.1-8b-instant").strip()
    smart = (
        os.getenv("GROQ_SMART_MODEL") or os.getenv("GROQ_AGENT_MODEL") or os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile"
    ).strip()
    for _cat, words in TAMIL_KEYWORDS.items():
        if any(w in (message or "") for w in words if len(w) > 1):
            q = f"{q} business"
            break
    stock_mkt = any(
        k in q for k in ("nse", "bse", "sensex", "nifty", "share price", "intraday", "macd", "rsi", "breakout")
    )
    biz = any(
        k in q
        for k in (
            "invoice",
            "inventory",
            "stock level",
            "profit",
            "expense",
            "farmer",
            "subsidy",
            "sale",
            "purchase",
            "payment",
            "gst",
        )
    )
    research = any(
        k in q for k in ("scheme", "govt", "government", "research", "market size", "how to", "what is", "find ")
    )
    if stock_mkt and not biz:
        return smart
    if research:
        return smart
    if biz:
        return fast
    return fast


def _model() -> str:
    return (os.getenv("GROQ_AGENT_MODEL") or os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()


def execute_tool_safe(
    *,
    name: str,
    args: dict[str, Any],
    user: Any,
    context_organization_id: int | None = None,
) -> dict[str, Any]:
    try:
        return execute_tool(
            name=name,
            args=args,
            user=user,
            context_organization_id=context_organization_id,
        )
    except Exception as exc:
        _log.exception("jarvis tool crashed: %s", name)
        return {"ok": False, "message": f"Tool {name} failed: {exc}"}


def _proposal_dict(index: int, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": index,
        "tool": name,
        "summary": _summarize_tool(name, args),
        "arguments": args,
    }


def _summarize_tool(name: str, args: dict[str, Any]) -> str:
    if name == "create_task":
        return f"Create task “{args.get('title', '')}” (priority {args.get('priority', 'P2')})"
    if name == "log_expense":
        return f"Log expense ₹{args.get('amount')} — {args.get('category')}"
    if name == "schedule_meeting":
        return f"Schedule meeting “{args.get('title')}” ({args.get('meeting_type')}) at {args.get('datetime')}"
    if name == "create_habit":
        return f"Create habit “{args.get('title')}”"
    if name == "create_invoice":
        return f"Create invoice for {args.get('customer_name')} — items {len(args.get('items') or [])}"
    if name == "add_stock":
        return f"Add {args.get('quantity')} {args.get('unit') or ''} of {args.get('item_name')} @ ₹{args.get('cost_price')}"
    if name == "record_sale":
        return f"Record sale ₹{args.get('amount')} via {args.get('payment_mode')}"
    if name == "add_business_expense":
        return f"Record ₹{args.get('amount')} expense — {args.get('category')}"
    if name == "add_farmer":
        return f"Add farmer {args.get('name')} — {args.get('scheme_name')}"
    if name == "update_subsidy_status":
        return f"Update subsidy to {args.get('status')} for id/name {args.get('farmer_id') or args.get('farmer_name')}"
    if name == "log_production":
        return f"Log {args.get('quantity_produced')} {args.get('unit') or ''} from {args.get('machine_name')}"
    if name == "mark_attendance":
        return f"Mark {args.get('worker_name')} as {args.get('status')}"
    return f"Run {name}({json.dumps(args, ensure_ascii=False)[:120]})"


def execute_tool(
    *,
    name: str,
    args: dict[str, Any],
    user: Any,
    context_organization_id: int | None = None,
) -> dict[str, Any]:
    uid = int(user.id)
    eff, err = resolve_jarvis_organization_id(user, context_organization_id)
    if err:
        return {"ok": False, "message": err}
    oid = eff
    try:
        if name in EXTENDED_TOOL_NAMES:
            return execute_jarvis_extended_tool(name=name, args=args, user=user, effective_org_id=oid)

        if name == "create_task":
            pr = (args.get("priority") or "P2").upper()
            if pr not in ("P1", "P2", "P3"):
                pr = "P2"
            dl = None
            if args.get("due_date"):
                raw = str(args["due_date"]).strip()
                dl = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dl.tzinfo is None:
                    dl = dl.replace(tzinfo=timezone.utc)
            ok, msg, mid, _cr = life_os_service.upsert_personal_mission(
                user_id=uid,
                mission_id=None,
                title=str(args.get("title") or "").strip(),
                description=None,
                deadline=dl,
                status="open",
                priority=pr,
            )
            out: dict[str, Any] = {"ok": ok, "message": msg, "mission_id": mid}
            if ok and mid:
                out["_undo"] = {"kind": "mission_cancel", "id": int(mid)}
            return out

        if name == "log_expense":
            amt = Decimal(str(args.get("amount") or "0"))
            ok, msg, eid = pcc.create_expense_sync(
                user_id=uid,
                amount=amt,
                currency="INR",
                category=str(args.get("category") or "general")[:64],
                subcategory="",
                spent_at=datetime.now(timezone.utc),
                title=str(args.get("note") or "")[:2000],
                notes_plain=str(args.get("note") or None),
                fernet=None,
            )
            out_e: dict[str, Any] = {"ok": ok, "message": msg, "expense_id": eid}
            if ok and eid:
                out_e["_undo"] = {"kind": "expense_delete", "id": int(eid)}
            return out_e

        if name == "schedule_meeting":
            raw_dt = str(args.get("datetime") or "").strip()
            st = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
            if st.tzinfo is None:
                st = st.replace(tzinfo=_IST)
            st = st.astimezone(timezone.utc)
            mt = str(args.get("meeting_type") or "other").strip().lower()[:32]
            if mt not in MEETING_TYPES:
                mt = "other"
            attendees = normalize_attendees(args.get("attendees") or [])
            factory = get_session_factory()
            if factory is None:
                return {"ok": False, "message": "no database"}
            with factory() as session:
                with session.begin():
                    row = create_meeting(
                        session,
                        user_id=uid,
                        organization_id=oid,
                        title=str(args.get("title") or "Meeting").strip()[:4000],
                        meeting_type=mt,
                        location_type="online",
                        location_name="",
                        location_address=None,
                        location_maps_url=None,
                        scheduled_at=st,
                        duration_minutes=int(args.get("duration_minutes") or 60),
                        priority="normal",
                        agenda=None,
                        arranged_by="self",
                        organizer_name=None,
                        organizer_phone=None,
                        organizer_email=None,
                        attendees_json=attendees,
                        reminder_minutes=30,
                        is_recurring=False,
                        recurrence_rule=None,
                    )
                    mid = int(row.id)
            try:
                from services.google_calendar_integration_service import try_push_new_meeting

                try_push_new_meeting(user_id=uid, organization_id=oid, meeting_id=mid)
            except Exception:
                pass
            gid: str | None = None
            try:
                with factory() as session:
                    rm = session.get(PersonalMeeting, mid)
                    if rm is not None and getattr(rm, "google_event_id", None):
                        gid = str(rm.google_event_id).strip() or None
            except Exception:
                pass
            return {
                "ok": True,
                "message": "meeting created",
                "meeting_id": mid,
                "_undo": meeting_undo_payload(mid, gid),
            }

        if name == "get_today_brief":
            data = pcc.build_today_brief_sync(user_id=uid, organization_id=oid, fernet=None)
            return {"ok": True, "brief": data}

        if name == "get_business_snapshot":
            if oid <= 0:
                return {"ok": True, "snapshot": {"ok": False, "note": "no organization"}}
            snap = compute_dashboard_summary_sync(oid)
            low = list_low_stock_alerts_sync(organization_id=oid, threshold_override=5.0)
            low_items = low.get("alerts") if isinstance(low, dict) else []
            if isinstance(snap, dict) and snap.get("ok"):
                snap = {**snap, "low_stock_alerts": low_items}
            return {"ok": True, "snapshot": snap}

        if name == "set_health_log":
            today = datetime.now(timezone.utc).date()
            sleep = args.get("sleep")
            water = args.get("water")
            stress = args.get("stress")
            ok, msg = life_os_service.upsert_health_metrics(
                user_id=uid,
                logged_on=today,
                sleep_hours=Decimal(str(sleep)) if sleep is not None else None,
                water_glasses=int(water) if water is not None else None,
                stress_1_10=int(stress) if stress is not None else None,
                fernet=None,
            )
            return {"ok": ok, "message": msg}

        if name == "search_inventory":
            q = (str(args.get("query") or "")).strip().lower()
            if oid <= 0 or not q:
                return {"ok": True, "items": []}
            factory = get_session_factory()
            if factory is None:
                return {"ok": False, "items": []}
            thr = Decimal("5")
            items: list[dict[str, Any]] = []
            seen: set[str] = set()
            with factory() as session:
                rows = session.execute(
                    select(Inventory)
                    .where(Inventory.organization_id == oid)
                    .where(func.lower(Inventory.sku_name).like(f"%{q}%"))
                    .limit(15)
                ).scalars().all()
                for r in rows:
                    key = (r.sku_name or "").lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    qty = float(r.quantity or 0)
                    items.append(
                        {
                            "sku_name": r.sku_name,
                            "quantity": qty,
                            "location": (r.location or "").strip(),
                            "low_stock_alert": qty < float(thr),
                        }
                    )
                rows2 = session.execute(
                    select(InventoryItem)
                    .where(InventoryItem.organization_id == oid)
                    .where(func.lower(InventoryItem.sku_name).like(f"%{q}%"))
                    .limit(15)
                ).scalars().all()
                for r in rows2:
                    key = (r.sku_name or "").lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    qty = float(r.quantity or 0)
                    items.append(
                        {
                            "sku_name": r.sku_name,
                            "quantity": qty,
                            "location": (r.location or "").strip(),
                            "low_stock_alert": qty < float(thr),
                        }
                    )
            return {"ok": True, "items": items[:20]}

        if name == "get_upcoming_emis":
            factory = get_session_factory()
            if factory is None:
                return {"ok": False, "emis": []}
            today_d = datetime.now(timezone.utc).date()
            horizon = today_d + timedelta(days=30)
            with factory() as session:
                rows = session.execute(
                    select(PersonalLoan)
                    .where(PersonalLoan.user_id == uid, PersonalLoan.is_closed.is_(False))
                    .order_by(PersonalLoan.next_due_date.asc())
                    .limit(24)
                ).scalars().all()
                emis = []
                for r in rows:
                    nd = r.next_due_date
                    if nd is None or nd < today_d or nd > horizon:
                        continue
                    emis.append(
                        {
                            "name": r.display_name,
                            "due": nd.isoformat(),
                            "emi": str(r.emi_amount) if r.emi_amount is not None else None,
                        }
                    )
            return {"ok": True, "emis": emis}

        if name == "create_habit":
            ok, msg, hid = life_os_service.create_personal_habit(
                user_id=uid,
                title=str(args.get("title") or "").strip(),
                goal_frequency=str(args.get("goal_frequency") or "daily").strip()[:128],
                category=(str(args.get("category")).strip()[:32] if args.get("category") else None),
            )
            out_h: dict[str, Any] = {"ok": ok, "message": msg, "habit_id": hid}
            if ok and hid:
                out_h["_undo"] = {"kind": "habit_deactivate", "id": int(hid)}
            return out_h

        return {"ok": False, "message": f"unknown tool {name}"}
    except Exception as e:
        _log.exception("tool %s failed", name)
        return {"ok": False, "message": str(e) or "tool error"}


def undo_last_action(*, user: Any) -> dict[str, Any]:
    from services.jarvis_undo_service import apply_undo_ops

    uid = int(user.id)
    ops = undo_pop_stack(uid)
    if not ops:
        return {"ok": False, "narrative": "", "error": "Nothing to undo yet.", "agent_mode": True}
    ok, msg = apply_undo_ops(user_id=uid, ops=ops)
    return {
        "ok": ok,
        "narrative": msg,
        "response": msg,
        "agent_mode": True,
        "action_intent": {"kind": "jarvis_undo", "success": ok},
    }


def _normalize_tool_call(tc: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(tc, dict):
        fn = tc.get("function") or {}
        name = str(fn.get("name") or "")
        arguments = fn.get("arguments") or "{}"
    else:
        fn = getattr(tc, "function", None)
        name = str(getattr(fn, "name", None) or "") if fn is not None else ""
        arguments = getattr(fn, "arguments", None) if fn is not None else "{}"
    if isinstance(arguments, str):
        try:
            args_dict = json.loads(arguments)
        except Exception:
            args_dict = {}
    else:
        args_dict = arguments if isinstance(arguments, dict) else {}
    return name, args_dict


def _tool_call_id(tc: Any, fallback: str) -> str:
    if isinstance(tc, dict):
        tid = tc.get("id")
        if tid:
            return str(tid)
    else:
        tid = getattr(tc, "id", None)
        if tid:
            return str(tid)
    return fallback


def _ctx_exec_from_stored(ctx_stored: int | None, context_organization_id: int | None) -> int | None:
    if ctx_stored is not None and int(ctx_stored) > 0:
        return int(ctx_stored)
    return context_organization_id


def run_agent(
    *,
    message: str,
    user: Any,
    agent_confirm: bool,
    agent_pending_id: str | None,
    context_organization_id: int | None = None,
    agent_confirm_tool_index: int | None = None,
    agent_reject_tool_index: int | None = None,
) -> dict[str, Any]:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        return {"ok": False, "narrative": "", "error": "GROQ_API_KEY not set"}

    uid = int(user.id)

    if not agent_confirm and context_organization_id is not None and int(context_organization_id) > 0:
        _, ctx_err = resolve_jarvis_organization_id(user, context_organization_id)
        if ctx_err:
            return {"ok": False, "narrative": "", "error": ctx_err, "agent_mode": True}

    # --- Partial reject: drop one proposed tool, keep pending batch ---
    if agent_pending_id and agent_reject_tool_index is not None:
        peeked = pending_peek(agent_pending_id, user_id=uid)
        if not peeked:
            return {"ok": False, "narrative": "", "error": "Pending action expired or invalid.", "agent_mode": True}
        calls, ctx_stored = peeked
        rj = int(agent_reject_tool_index)
        if rj < 0 or rj >= len(calls):
            return {"ok": False, "narrative": "", "error": "Invalid reject index.", "agent_mode": True}
        new_calls = calls[:rj] + calls[rj + 1 :]
        ctx_o = ctx_stored if ctx_stored and int(ctx_stored) > 0 else None
        if new_calls:
            pending_set(
                agent_pending_id,
                user_id=uid,
                tool_calls=new_calls,
                ttl_sec=_PENDING_TTL_SEC,
                context_organization_id=ctx_o,
            )
        else:
            pending_delete(agent_pending_id, user_id=uid)
        proposals = [_proposal_dict(i, c["name"], c["arguments"]) for i, c in enumerate(new_calls)]
        msg = f"Rejected proposal #{rj + 1}. {len(new_calls)} action(s) still pending."
        return {
            "ok": True,
            "narrative": msg,
            "response": msg,
            "agent_mode": True,
            "needs_confirmation": bool(new_calls),
            "agent_pending_id": agent_pending_id if new_calls else None,
            "proposals": proposals,
            "action_intent": {"kind": "jarvis_partial_reject", "success": True},
        }

    # --- Partial accept: execute one tool, shrink pending ---
    if agent_pending_id and agent_confirm_tool_index is not None:
        peeked = pending_peek(agent_pending_id, user_id=uid)
        if not peeked:
            return {"ok": False, "narrative": "", "error": "Pending action expired or invalid.", "agent_mode": True}
        calls, ctx_stored = peeked
        ci = int(agent_confirm_tool_index)
        if ci < 0 or ci >= len(calls):
            return {"ok": False, "narrative": "", "error": "Invalid confirm index.", "agent_mode": True}
        ctx_exec = _ctx_exec_from_stored(ctx_stored, context_organization_id)
        one = calls[ci]
        name = str(one.get("name") or "")
        raw_args = one.get("arguments") or {}
        if isinstance(raw_args, str):
            try:
                raw_args = json.loads(raw_args)
            except Exception:
                raw_args = {}
        args_d = raw_args if isinstance(raw_args, dict) else {}
        out = execute_tool_safe(name=name, args=args_d, user=user, context_organization_id=ctx_exec)
        undo_ops: list[dict[str, Any]] = []
        uop = out.pop("_undo", None) if isinstance(out, dict) else None
        if isinstance(uop, dict):
            undo_ops.append(uop)
        if out.get("ok") and undo_ops:
            undo_store(uid, undo_ops)
        rest = calls[:ci] + calls[ci + 1 :]
        ctx_o = ctx_stored if ctx_stored and int(ctx_stored) > 0 else None
        if rest:
            pending_set(
                agent_pending_id,
                user_id=uid,
                tool_calls=rest,
                ttl_sec=_PENDING_TTL_SEC,
                context_organization_id=ctx_o,
            )
        else:
            pending_delete(agent_pending_id, user_id=uid)
        results = [{"tool": name, "result": out}]
        proposals = [_proposal_dict(i, c["name"], c["arguments"]) for i, c in enumerate(rest)]
        lines = [f"Executed {name}: {json.dumps(out, default=str)[:500]}"]
        if rest:
            lines.append(f"{len(rest)} action(s) still need confirmation.")
        narrative = "\n".join(lines)
        return {
            "ok": bool(out.get("ok")),
            "narrative": narrative,
            "response": narrative,
            "agent_mode": True,
            "tool_results": results,
            "needs_confirmation": bool(rest),
            "agent_pending_id": agent_pending_id if rest else None,
            "proposals": proposals,
            "action_intent": {"kind": "jarvis_partial_confirm", "success": bool(out.get("ok"))},
        }

    # --- Confirm all pending (legacy) ---
    if agent_confirm and agent_pending_id:
        popped = pending_pop(agent_pending_id, user_id=uid)
        if not popped:
            return {"ok": False, "narrative": "", "error": "Pending action expired or invalid."}
        calls, ctx_stored = popped
        ctx_exec = _ctx_exec_from_stored(ctx_stored, context_organization_id)
        results: list[dict[str, Any]] = []
        undo_ops: list[dict[str, Any]] = []
        for c in calls:
            name = c.get("name") or ""
            raw_args = c.get("arguments") or {}
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except Exception:
                    raw_args = {}
            out = execute_tool_safe(
                name=name,
                args=raw_args if isinstance(raw_args, dict) else {},
                user=user,
                context_organization_id=ctx_exec,
            )
            uop = out.pop("_undo", None) if isinstance(out, dict) else None
            if isinstance(uop, dict):
                undo_ops.append(uop)
            results.append({"tool": name, "result": out})
        ok_all = all(r["result"].get("ok") for r in results if isinstance(r.get("result"), dict))
        if ok_all and undo_ops:
            undo_store(uid, undo_ops)
        lines = [f"Executed {len(results)} action(s)."]
        for r in results:
            lines.append(f"- {r['tool']}: {json.dumps(r['result'], default=str)[:500]}")
        return {
            "ok": True,
            "narrative": "\n".join(lines),
            "response": "\n".join(lines),
            "agent_mode": True,
            "tool_results": results,
            "action_intent": {"kind": "jarvis_agent", "success": ok_all},
        }

    mem_entries = fetch_memory_entries_sync(user_id=uid, limit=8)
    mem_lines = [e["line"] for e in mem_entries]
    mem_keys_used = [e["key"] for e in mem_entries]
    mem_block = "\n".join(mem_lines) if mem_lines else "(none yet)"
    lang_note = "The user wrote in Tamil — reply in Tamil. " if _looks_tamil(message) else ""
    routed_model, tools_subset, route_category = merge_route_tool_specs(message.strip(), TOOL_SPECS)
    system = (
        "You are Thiramai Jarvis, a business AI assistant for an Indian entrepreneur. "
        f"{lang_note}"
        "You understand Tamil and English; mirror the user's language. "
        "Use Indian Rupees (₹) and local business context (lakhs/crores when natural).\n"
        f"User memory hints:\n{mem_block}\n\n"
        f"Routing: focus area = {route_category}. Only the supplied tools are available.\n"
        "Read-only tools run immediately in the agent loop. "
        "Mutating tools require UI confirmation — still call them when appropriate. "
        "For business_org_id / org_id use the active organization when not specified. "
        "Today UTC date: "
        f"{datetime.now(timezone.utc).date().isoformat()}."
    )
    client = Groq(api_key=key)
    max_steps = max(1, min(int((os.getenv("THIRAMAI_JARVIS_MAX_STEPS") or "5").strip()), 12))

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": message.strip()[:8000]},
    ]
    all_auto_results: list[dict[str, Any]] = []
    last_choice_content = ""

    for step in range(max_steps):
        try:
            completion = client.chat.completions.create(
                model=routed_model,
                messages=messages,
                tools=tools_subset,
                tool_choice="auto",
                temperature=0.3,
                max_tokens=1024,
            )
        except Exception as e:
            _log.warning("jarvis groq step %s failed: %s", step, e)
            return {"ok": False, "narrative": "", "error": str(e) or "groq error", "agent_mode": True}

        choice = completion.choices[0].message
        dumped = choice.model_dump(mode="json") if hasattr(choice, "model_dump") else {}
        tool_calls = dumped.get("tool_calls") or getattr(choice, "tool_calls", None) or []
        last_choice_content = (dumped.get("content") or getattr(choice, "content", None) or "").strip()

        if not tool_calls:
            bump_memory_usage_sync(user_id=uid, memory_keys=mem_keys_used)
            learn_from_turn_sync(
                user_id=uid,
                user_message=message.strip(),
                assistant_text=last_choice_content,
                tool_results=all_auto_results,
            )
            return {
                "ok": True,
                "narrative": last_choice_content or "Done.",
                "response": last_choice_content or "Done.",
                "agent_mode": True,
                "action_intent": {"kind": "jarvis_chat", "success": True},
                "groq_model": routed_model,
                "route_category": route_category,
                "route_tool_count": len(tools_subset),
            }

        serialized_step: list[dict[str, Any]] = []
        for i, tc in enumerate(tool_calls):
            tid = _tool_call_id(tc, f"jarvis_{step}_{i}")
            n, a = _normalize_tool_call(tc)
            serialized_step.append({"id": tid, "name": n, "arguments": a})

        auto_calls = [x for x in serialized_step if x["name"] in AUTO_EXECUTE_TOOL_NAMES]
        mut_calls = [x for x in serialized_step if x["name"] not in AUTO_EXECUTE_TOOL_NAMES]

        step_tool_results: list[dict[str, Any]] = []
        for c in auto_calls:
            out = execute_tool_safe(
                name=c["name"],
                args=c["arguments"],
                user=user,
                context_organization_id=context_organization_id,
            )
            rec = {"tool": c["name"], "result": out}
            step_tool_results.append(rec)
            all_auto_results.append(rec)

        if mut_calls:
            proposals = [_proposal_dict(i, c["name"], c["arguments"]) for i, c in enumerate(mut_calls)]
            pending_id = secrets.token_urlsafe(24)
            pending_mut = [{"name": c["name"], "arguments": c["arguments"]} for c in mut_calls]
            pending_set(
                pending_id,
                user_id=uid,
                tool_calls=pending_mut,
                ttl_sec=_PENDING_TTL_SEC,
                context_organization_id=context_organization_id,
            )
            intro_parts: list[str] = []
            if step_tool_results:
                intro_parts.append("Fetched:")
                for r in step_tool_results:
                    intro_parts.append(f"• {r['tool']}: {json.dumps(r['result'], default=str)[:320]}")
            intro_parts.append("Confirm the following actions (each card can be accepted or rejected):")
            intro_parts.extend(f"• {p['summary']}" for p in proposals)
            intro = "\n".join(intro_parts)
            bump_memory_usage_sync(user_id=uid, memory_keys=mem_keys_used)
            learn_from_turn_sync(
                user_id=uid,
                user_message=message.strip(),
                assistant_text=intro,
                tool_results=all_auto_results,
            )
            return {
                "ok": True,
                "narrative": intro,
                "response": intro,
                "agent_mode": True,
                "needs_confirmation": True,
                "agent_pending_id": pending_id,
                "proposals": proposals,
                "tool_results": all_auto_results,
                "action_intent": {"kind": "jarvis_pending", "success": True},
                "groq_model": routed_model,
                "route_category": route_category,
                "route_tool_count": len(tools_subset),
            }

        assistant_tool_calls = [
            {
                "id": c["id"],
                "type": "function",
                "function": {
                    "name": c["name"],
                    "arguments": json.dumps(c["arguments"], ensure_ascii=False, default=str),
                },
            }
            for c in serialized_step
        ]
        asst_content: str | None = last_choice_content or None
        if asst_content == "":
            asst_content = None
        messages.append({"role": "assistant", "content": asst_content, "tool_calls": assistant_tool_calls})
        for c, tr in zip(auto_calls, step_tool_results):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": c["id"],
                    "content": json.dumps(tr["result"], default=str),
                }
            )

    bump_memory_usage_sync(user_id=uid, memory_keys=mem_keys_used)
    learn_from_turn_sync(
        user_id=uid,
        user_message=message.strip(),
        assistant_text=last_choice_content,
        tool_results=all_auto_results,
    )
    tail = last_choice_content or "Reached max agent steps; see tool results."
    lines = [tail, "", "Tool results:"]
    for r in all_auto_results:
        lines.append(f"- {r['tool']}: {json.dumps(r['result'], default=str)[:400]}")
    narrative = "\n".join(lines)
    return {
        "ok": True,
        "narrative": narrative,
        "response": narrative,
        "agent_mode": True,
        "tool_results": all_auto_results,
        "action_intent": {"kind": "jarvis_agent", "success": True},
        "groq_model": routed_model,
        "route_category": route_category,
        "route_tool_count": len(tools_subset),
        "agent_loop_exhausted": True,
    }
