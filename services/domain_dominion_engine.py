"""
Domain domination: vertical focus, knowledge aggregation, templates, opportunity pipeline,
revenue tracking, and weekly strategy loop.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.database import get_session_factory
from core.db.models import DomainDominionProfile, DomainRevenueLedger
from services.integration_engine import SUPPORTED_TYPES, list_integrations
from services.learning_engine import record_outcome
from services.opportunity_engine import (
    approve_opportunity,
    execute_opportunity,
    list_opportunities,
    scan_all_opportunities,
)
from services.revenue_engine import revenue_snapshot

ALLOWED_DOMAINS = frozenset(
    {
        "agriculture",
        "trading",
        "manufacturing",
        "business",
        "services",
        "retail",
        "logistics",
        "energy",
    }
)

# Opportunity engine types considered in-domain (when not tagged in metadata)
_OPP_BY_DOMAIN: dict[str, frozenset[str]] = {
    "trading": frozenset({"trading", "arbitrage"}),
    "agriculture": frozenset({"business", "arbitrage"}),
    "manufacturing": frozenset({"business", "arbitrage"}),
    "business": frozenset({"business", "arbitrage", "trading"}),
    "retail": frozenset({"business", "arbitrage"}),
    "services": frozenset({"business", "arbitrage"}),
    "logistics": frozenset({"business", "arbitrage"}),
    "energy": frozenset({"business", "arbitrage"}),
}

_DOMAIN_ACTION_TEMPLATES: dict[str, dict[str, str]] = {
    "sourcing": {
        "agriculture": "Research crop suppliers and input costs for our region; compare 3 suppliers and request quotes. Summarize TCO and delivery risk.",
        "trading": "Screen liquid symbols for a swing setup with max 1% account risk; verify spread and slippage. Do not place live orders without confirmation.",
        "manufacturing": "Identify alternative raw material sources and MoQ; estimate landed cost and lead time; flag single-source risks.",
        "default": "Run supplier research: identify 3 vendors, request quotes, and build a TCO table with delivery and payment terms.",
    },
    "pricing": {
        "agriculture": "Review commodity benchmark vs our realized prices; suggest farm-gate and wholesale pricing for next 30 days with a margin buffer.",
        "trading": "Re-assess position sizing; compute breakeven and R-multiples; set alerts for key technical levels (no order placement).",
        "manufacturing": "Recompute product COGS, overhead allocation, and recommended list price; flag SKUs with margin below target.",
        "default": "Benchmark competitors, adjust pricing ladder, and document margin assumptions for top SKUs.",
    },
    "selling": {
        "default": "List top 5 deal priorities for this week: follow-ups, proposals due, and pipeline conversion risks.",
    },
    "marketing": {
        "default": "Draft a 7-day outreach plan: 2 content themes, 1 offer, 3 follow-up touchpoints, and 1 retargeting angle.",
    },
}

# Catalog for real-world connections (use with POST /integrations — extended types in integration_engine)
CONNECTOR_CATALOG: list[dict[str, Any]] = [
    {"type": "email", "label": "Email (suppliers, customers, marketplaces)"},
    {"type": "whatsapp", "label": "WhatsApp Business / messaging"},
    {"type": "sms", "label": "SMS transactions & alerts"},
    {"type": "marketplace", "label": "Marketplace or storefront API (config in JSON)"},
    {"type": "suppliers", "label": "Supplier directory / RFQ API"},
    {"type": "messaging", "label": "Slack, Teams, webhooks for ops"},
]


def _coerce_domain(raw: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "", str(raw or "").lower().strip())
    if s in ALLOWED_DOMAINS:
        return s
    return "business"


def _session():
    return get_session_factory()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create_profile(*, user_id: int, organization_id: int) -> dict[str, Any]:
    factory = _session()
    if factory is None:
        return {"id": 0, "active_domain": "business", "enabled": False, "knowledge_json": {}}
    with factory() as session:
        row = session.execute(
            select(DomainDominionProfile).where(
                DomainDominionProfile.user_id == int(user_id),
                DomainDominionProfile.organization_id == int(organization_id),
            )
        ).scalar_one_or_none()
        if row is None:
            try:
                row = DomainDominionProfile(
                    user_id=int(user_id),
                    organization_id=int(organization_id),
                    active_domain="business",
                )
                session.add(row)
                session.commit()
                session.refresh(row)
            except IntegrityError:
                session.rollback()
                return {
                    "id": 0,
                    "user_id": int(user_id),
                    "organization_id": int(organization_id),
                    "active_domain": "business",
                    "enabled": False,
                    "knowledge_json": {},
                    "meta_json": {},
                    "last_weekly_review_at": None,
                    "updated_at": None,
                }
        return _profile_to_dict(row)


def _profile_to_dict(row: DomainDominionProfile) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "user_id": int(row.user_id),
        "organization_id": int(row.organization_id),
        "active_domain": str(row.active_domain or "business"),
        "enabled": bool(row.enabled),
        "knowledge_json": row.knowledge_json or {},
        "meta_json": row.meta_json or {},
        "last_weekly_review_at": row.last_weekly_review_at.isoformat() if row.last_weekly_review_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def set_active_domain(
    *, user_id: int, organization_id: int, domain: str, enabled: bool | None = None
) -> dict[str, Any] | None:
    d = _coerce_domain(domain)
    factory = _session()
    if factory is None:
        return None
    with factory() as session:
        row = session.execute(
            select(DomainDominionProfile).where(
                DomainDominionProfile.user_id == int(user_id),
                DomainDominionProfile.organization_id == int(organization_id),
            )
        ).scalar_one_or_none()
        if row is None:
            row = DomainDominionProfile(user_id=int(user_id), organization_id=int(organization_id))
            session.add(row)
        row.active_domain = d
        if enabled is not None:
            row.enabled = bool(enabled)
        row.updated_at = _now()
        session.commit()
        session.refresh(row)
        return _profile_to_dict(row)


def merge_knowledge(
    *,
    user_id: int,
    organization_id: int,
    section: str,
    items: list[dict[str, Any]] | list[str] | str,
) -> dict[str, Any] | None:
    sec = str(section or "tools").lower()[:32]
    factory = _session()
    if factory is None:
        return None
    with factory() as session:
        row = session.execute(
            select(DomainDominionProfile).where(
                DomainDominionProfile.user_id == int(user_id),
                DomainDominionProfile.organization_id == int(organization_id),
            )
        ).scalar_one_or_none()
        if row is None:
            row = DomainDominionProfile(user_id=int(user_id), organization_id=int(organization_id))
            session.add(row)
        k = dict(row.knowledge_json or {})
        bucket: list[Any] = list(k.get(sec) or [])
        if isinstance(items, str):
            if items.strip():
                bucket.append({"text": items.strip()})
        else:
            for it in items or []:
                if isinstance(it, dict):
                    bucket.append(it)
                else:
                    bucket.append({"text": str(it)})
        k[sec] = bucket[-200:]
        row.knowledge_json = k
        row.updated_at = _now()
        session.commit()
        session.refresh(row)
        return _profile_to_dict(row)


def get_action_templates(*, user_id: int, organization_id: int) -> dict[str, Any]:
    p = get_or_create_profile(user_id=int(user_id), organization_id=int(organization_id))
    d = p.get("active_domain") or "business"
    out: dict[str, str] = {}
    for name, m in _DOMAIN_ACTION_TEMPLATES.items():
        out[name] = str(m.get(d) or m.get("default") or "")
    return {"ok": True, "domain": d, "templates": out}


def list_domain_connectors(*, user_id: int) -> dict[str, Any]:
    ex = {str(x.get("type") or "") for x in (list_integrations(int(user_id)) or [])}
    return {
        "ok": True,
        "core_channels": sorted(SUPPORTED_TYPES),
        "domain_extended_types": [x["type"] for x in CONNECTOR_CATALOG if str(x.get("type")) not in {"email", "whatsapp", "sms"}],
        "catalog": CONNECTOR_CATALOG,
        "user_enabled_types": sorted(x for x in ex if x),
    }


def record_domain_revenue_event(
    *,
    user_id: int,
    organization_id: int,
    event_type: str,
    amount: float,
    domain: str = "",
    ref_type: str | None = None,
    ref_id: int | None = None,
    note: str = "",
    currency: str = "INR",
) -> dict[str, Any] | None:
    et = str(event_type or "").lower()[:24]
    if et not in ("income", "cost", "adjustment"):
        et = "adjustment"
    p = get_or_create_profile(user_id=int(user_id), organization_id=int(organization_id))
    d = str(domain or p.get("active_domain") or "business")
    pid = int(p.get("id") or 0) or None
    factory = _session()
    if factory is None:
        return None
    with factory() as session:
        row = DomainRevenueLedger(
            user_id=int(user_id),
            organization_id=int(organization_id),
            profile_id=pid,
            domain=d[:64],
            event_type=et,
            amount=float(amount or 0.0),
            currency=str(currency or "INR")[:8],
            ref_type=str(ref_type)[:32] if ref_type else None,
            ref_id=int(ref_id) if ref_id is not None else None,
            note=(note or "")[:2000] or None,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "id": int(row.id)}


def domain_pnl_summary(*, user_id: int, organization_id: int, hours: int = 7 * 24) -> dict[str, Any]:
    p = get_or_create_profile(user_id=int(user_id), organization_id=int(organization_id))
    dname = p.get("active_domain") or "business"
    rev0 = revenue_snapshot(int(user_id), hours=hours)
    factory = _session()
    inc = 0.0
    cost = 0.0
    if factory is not None:
        since = _now() - timedelta(hours=max(1, int(hours)))
        with factory() as session:
            for r in (
                session.execute(
                    select(DomainRevenueLedger).where(
                        DomainRevenueLedger.user_id == int(user_id),
                        DomainRevenueLedger.created_at >= since,
                    )
                )
                .scalars()
                .all()
            ):
                if str(r.domain) and str(r.domain) not in (dname, "all", ""):
                    if str(r.domain) != dname:
                        continue
                amt = float(r.amount or 0.0)
                t = str(r.event_type or "")
                if t == "income":
                    inc += amt
                elif t == "cost":
                    cost += amt
                else:
                    inc += amt
    return {
        "ok": True,
        "active_domain": dname,
        "window_hours": int(hours),
        "domain_ledger": {"income": round(inc, 2), "cost": round(cost, 2), "net": round(inc - cost, 2)},
        "revenue_engine_snapshot": rev0,
    }


def _opp_matches_domain(opp: dict[str, Any], domain: str) -> bool:
    meta = opp.get("metadata_json") if isinstance(opp.get("metadata_json"), dict) else {}
    if str(meta.get("domain") or "") == str(domain):
        return True
    t = str(opp.get("type") or "")
    want = _OPP_BY_DOMAIN.get(domain) or _OPP_BY_DOMAIN["business"]
    return t in want


def run_domain_opportunity_pipeline(
    *, user_id: int, organization_id: int, role_name: str, max_execute: int = 1, scan_first: bool = True
) -> dict[str, Any]:
    p = get_or_create_profile(user_id=int(user_id), organization_id=int(organization_id))
    if not p.get("enabled", True):
        return {"ok": True, "skipped": True, "reason": "domain_dominion disabled"}
    dom = str(p.get("active_domain") or "business")
    scan: dict[str, Any] = {}
    if scan_first:
        try:
            scan = scan_all_opportunities(int(user_id), int(organization_id)) or {}
        except Exception as exc:  # pragma: no cover
            scan = {"ok": False, "error": str(exc)}
    opps = [
        o
        for o in list_opportunities(int(user_id), 50)
        if _opp_matches_domain(o, dom) and str(o.get("status") or "") in ("new", "approved")
    ][:10]
    opps.sort(key=lambda o: float(o.get("score") or 0), reverse=True)
    out: list[dict[str, Any]] = []
    n = 0
    for o in opps:
        if n >= max(0, int(max_execute)):
            break
        if str(o.get("status") or "") == "new":
            approve_opportunity(int(user_id), int(o.get("id") or 0))
        ex = execute_opportunity(
            int(user_id),
            int(organization_id),
            str(role_name or "owner"),
            int(o.get("id") or 0),
        )
        n += 1
        if ex and ex.get("ok"):
            realized = float((ex or {}).get("realized_profit") or 0.0)
            record_domain_revenue_event(
                user_id=int(user_id),
                organization_id=int(organization_id),
                event_type="income",
                amount=realized,
                domain=dom,
                ref_type="opportunity",
                ref_id=int(o.get("id") or 0),
                note="Domain pipeline: opportunity execution (estimated realized profit)",
            )
        out.append({"opportunity": o, "result": ex})
    return {
        "ok": True,
        "domain": dom,
        "scan": scan,
        "executed": n,
        "stages": ["detect", "evaluate", "execute", "track_profit"],
        "details": out,
    }


def run_weekly_domain_strategy_review(*, user_id: int, organization_id: int) -> dict[str, Any]:
    p0 = get_or_create_profile(user_id=int(user_id), organization_id=int(organization_id))
    dom = str(p0.get("active_domain") or "business")
    pnl = domain_pnl_summary(user_id=int(user_id), organization_id=int(organization_id), hours=7 * 24)
    opps = list_opportunities(int(user_id), 30)
    failed = sum(1 for o in opps if str(o.get("status") or "") in ("rejected",))
    k = p0.get("knowledge_json") or {}
    improvements: list[str] = []
    net = float(pnl.get("domain_ledger", {}).get("net", 0) or 0)
    if net < 0:
        improvements.append("Net domain P&L is negative: tighten cost controls and re-check pricing.")
    if failed:
        improvements.append("Review rejected opportunities: refine filters or data quality.")
    if not (k.get("workflows") or []):
        improvements.append("Add at least one documented workflow under knowledge.workflows")
    if not (k.get("regulations") or []):
        improvements.append("Add regulatory or compliance notes for this domain in knowledge.regulations")
    rec = {
        "week_ending": _now().isoformat(),
        "active_domain": dom,
        "pnl": pnl,
        "open_opportunities": len([x for x in opps if str(x.get("status") or "") == "new"]),
        "rejected_count": failed,
        "improvements": improvements[:8],
    }
    factory = _session()
    if factory is not None:
        with factory() as session:
            row = session.execute(
                select(DomainDominionProfile).where(
                    DomainDominionProfile.user_id == int(user_id),
                    DomainDominionProfile.organization_id == int(organization_id),
                )
            ).scalar_one_or_none()
            if row is not None:
                m = dict(row.meta_json or {})
                hist = list(m.get("weekly_reviews", []))[-11:]
                hist.append(rec)
                m["weekly_reviews"] = hist
                row.meta_json = m
                row.last_weekly_review_at = _now()
                row.updated_at = _now()
                session.commit()
    try:
        record_outcome(
            user_id=int(user_id),
            organization_id=int(organization_id),
            source_type="domain_dominion",
            source_id=None,
            input_data={"action": "weekly_strategy_review", "domain": dom},
            outcome=rec,
        )
    except Exception:
        pass
    return {"ok": True, "review": rec, "knowledge_suggestions": improvements}
