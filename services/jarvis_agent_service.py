"""
Groq tool-calling agent for THIRAMAI actions (missions, expenses, meetings, brief, etc.).

Two-step flow when tools are requested:
1. ``needs_confirmation`` + ``agent_pending_id`` (user approves in UI).
2. Same message + ``agent_confirm=True`` + ``agent_pending_id`` executes tools.
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
from core.db.models import Inventory, InventoryItem, PersonalLoan, PersonalMeeting
from core.jarvis_pending_redis import pending_pop, pending_set, undo_pop_stack, undo_store
from services import life_os_service
from services import personal_command_center_service as pcc
from services.analytics_service import compute_dashboard_summary_sync, list_low_stock_alerts_sync
from services.jarvis_undo_service import meeting_undo_payload
from services.personal_meetings_service import MEETING_TYPES, create_meeting, normalize_attendees

_log = logging.getLogger("thiramai.jarvis_agent")

_PENDING_TTL_SEC = 600
_IST = ZoneInfo("Asia/Kolkata")

TOOL_SPECS: list[dict[str, Any]] = [
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


def _model() -> str:
    return (os.getenv("GROQ_AGENT_MODEL") or os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()


def _summarize_tool(name: str, args: dict[str, Any]) -> str:
    if name == "create_task":
        return f"Create task “{args.get('title', '')}” (priority {args.get('priority', 'P2')})"
    if name == "log_expense":
        return f"Log expense ₹{args.get('amount')} — {args.get('category')}"
    if name == "schedule_meeting":
        return f"Schedule meeting “{args.get('title')}” ({args.get('meeting_type')}) at {args.get('datetime')}"
    if name == "create_habit":
        return f"Create habit “{args.get('title')}”"
    return f"Run {name}({json.dumps(args, ensure_ascii=False)[:120]})"


def execute_tool(
    *,
    name: str,
    args: dict[str, Any],
    user: Any,
) -> dict[str, Any]:
    uid = int(user.id)
    oid = int(user.organization_id)
    try:
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
            low = list_low_stock_alerts_sync(oid, threshold=5, limit=25)
            if isinstance(snap, dict) and snap.get("ok"):
                snap = {**snap, "low_stock_alerts": low}
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


def run_agent(
    *,
    message: str,
    user: Any,
    agent_confirm: bool,
    agent_pending_id: str | None,
) -> dict[str, Any]:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        return {"ok": False, "narrative": "", "error": "GROQ_API_KEY not set"}

    uid = int(user.id)

    if agent_confirm and agent_pending_id:
        calls = pending_pop(agent_pending_id, user_id=uid)
        if not calls:
            return {"ok": False, "narrative": "", "error": "Pending action expired or invalid."}
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
            out = execute_tool(name=name, args=raw_args if isinstance(raw_args, dict) else {}, user=user)
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

    system = (
        "You are THIRAMAI Jarvis, a concise assistant. Use tools when the user wants actions. "
        "For destructive or financial actions, still call the tool — the system will ask the user to confirm first. "
        "Prefer one tool call per user turn when possible. Today UTC date context: "
        f"{datetime.now(timezone.utc).date().isoformat()}."
    )
    client = Groq(api_key=key)
    try:
        completion = client.chat.completions.create(
            model=_model(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": message.strip()[:8000]},
            ],
            tools=TOOL_SPECS,
            tool_choice="auto",
            temperature=0.3,
            max_tokens=1024,
        )
    except Exception as e:
        return {"ok": False, "narrative": "", "error": str(e) or "groq error"}

    choice = completion.choices[0].message
    dumped = choice.model_dump(mode="json") if hasattr(choice, "model_dump") else {}
    tool_calls = dumped.get("tool_calls") or getattr(choice, "tool_calls", None) or []
    if not tool_calls:
        text = (getattr(choice, "content", None) or "").strip() or "Done."
        return {
            "ok": True,
            "narrative": text,
            "response": text,
            "agent_mode": True,
            "action_intent": {"kind": "jarvis_chat", "success": True},
        }

    serialized: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    for tc in tool_calls:
        if isinstance(tc, dict):
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            arguments = fn.get("arguments") or "{}"
        else:
            fn = getattr(tc, "function", None)
            name = getattr(fn, "name", None) if fn is not None else ""
            arguments = getattr(fn, "arguments", None) if fn is not None else "{}"
        if isinstance(arguments, str):
            try:
                args_dict = json.loads(arguments)
            except Exception:
                args_dict = {}
        else:
            args_dict = arguments if isinstance(arguments, dict) else {}
        serialized.append({"name": name, "arguments": args_dict})
        proposals.append(
            {
                "tool": name,
                "summary": _summarize_tool(name, args_dict),
                "arguments": args_dict,
            }
        )

    pending_id = secrets.token_urlsafe(24)
    pending_set(pending_id, user_id=uid, tool_calls=serialized, ttl_sec=_PENDING_TTL_SEC)

    intro = (
        "I'll run the following — please confirm:\n"
        + "\n".join(f"• {p['summary']}" for p in proposals)
    )
    return {
        "ok": True,
        "narrative": intro,
        "response": intro,
        "agent_mode": True,
        "needs_confirmation": True,
        "agent_pending_id": pending_id,
        "proposals": proposals,
        "action_intent": {"kind": "jarvis_pending", "success": True},
    }
