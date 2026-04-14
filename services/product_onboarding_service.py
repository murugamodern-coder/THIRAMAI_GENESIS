"""Onboarding state, demo seed, wow insights (server-side source of truth)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import Organization, PersonalExpense, PersonalMission, User
from services.cross_domain_analyzer import analyze_cross_domain
from services.org_service import normalize_plan

_log = logging.getLogger("thiramai.product_onboarding")

DEFAULT_PROFILE: dict[str, Any] = {
    "onboarding": {"step": 0, "business_done": False, "expense_done": False, "insights_done": False},
    "demo_seeded": False,
    "wow_shown": False,
}


def _merge_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULT_PROFILE)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = {**out[k], **v}
            else:
                out[k] = v
    return out


def get_product_profile(session: Session, user_id: int) -> dict[str, Any]:
    u = session.get(User, int(user_id))
    if u is None:
        return dict(DEFAULT_PROFILE)
    return _merge_profile(getattr(u, "product_profile", None))


def save_product_profile(session: Session, user_id: int, profile: dict[str, Any]) -> None:
    u = session.get(User, int(user_id))
    if u is None:
        return
    merged = _merge_profile(getattr(u, "product_profile", None))
    for k, v in profile.items():
        if k == "onboarding" and isinstance(v, dict) and isinstance(merged.get("onboarding"), dict):
            merged["onboarding"] = {**merged["onboarding"], **v}
        else:
            merged[k] = v
    u.product_profile = merged
    session.add(u)


def seed_demo_data_sync(*, user_id: int, organization_id: int) -> dict[str, Any]:
    """Idempotent-ish demo rows for first-run wow (personal expense + mission)."""
    uid = int(user_id)
    oid = int(organization_id)
    if uid <= 0:
        return {"ok": False, "error": "invalid user"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database unavailable"}
    with factory() as session:
        with session.begin():
            u = session.get(User, uid)
            if u is None:
                return {"ok": False, "error": "user not found"}
            prof = _merge_profile(getattr(u, "product_profile", None))
            if prof.get("demo_seeded"):
                return {"ok": True, "note": "already_seeded"}
            now = datetime.now(timezone.utc)
            session.add(
                PersonalExpense(
                    user_id=uid,
                    currency="INR",
                    category="Food",
                    subcategory="demo",
                    spent_at=now,
                    title="Demo: team lunch (sample)",
                    amount=Decimal("850.00"),
                )
            )
            session.add(
                PersonalMission(
                    user_id=uid,
                    title="Demo: follow up top invoice (sample)",
                    description="Replace this with a real mission when you go live.",
                    status="open",
                    priority="P2",
                )
            )
            prof["demo_seeded"] = True
            u.product_profile = prof
    _log.info("demo seeded user=%s org=%s", uid, oid)
    return {"ok": True, "seeded": True}


def build_wow_insights_sync(*, user_id: int, organization_id: int) -> dict[str, Any]:
    """Three punchy insights for first session (cross-domain when healthy, else curated fallbacks)."""
    uid = int(user_id)
    oid = int(organization_id)
    insights: list[dict[str, str]] = []
    cd: dict[str, Any] = {}
    try:
        cd = analyze_cross_domain(uid, organization_id=oid, financial_snapshot=None)
        for x in (cd.get("top_insights") or [])[:3]:
            if isinstance(x, dict) and (x.get("title") or x.get("detail")):
                insights.append(
                    {
                        "title": str(x.get("title") or "Insight"),
                        "detail": str(x.get("detail") or "")[:400],
                    }
                )
    except Exception as exc:
        _log.debug("wow cross_domain: %s", exc)
    while len(insights) < 3:
        insights.append(
            {
                "title": ["Cash runway", "Collections", "Margin focus"][len(insights)],
                "detail": [
                    "Link personal spend + EMIs + business opex in one view — upgrade to Pro for full automation.",
                    "Unpaid invoices are the fastest lever when cash is tight.",
                    "Double down on the org with the best gross margin this month.",
                ][len(insights)],
            }
        )
    cap = cd.get("captain_message")
    return {"ok": True, "insights": insights[:3], "captain_message": (cap or "")[:500]}


def get_bootstrap_sync(*, user_id: int, organization_id: int) -> dict[str, Any]:
    uid = int(user_id)
    oid = int(organization_id)
    factory = get_session_factory()
    if factory is None or uid <= 0:
        return {"ok": False, "error": "unavailable"}
    with factory() as session:
        prof = get_product_profile(session, uid)
        org = session.get(Organization, oid) if oid > 0 else None
        plan = normalize_plan(getattr(org, "plan", None) if org else None)
        n_exp = int(
            session.scalar(select(func.count()).select_from(PersonalExpense).where(PersonalExpense.user_id == uid)) or 0
        )
        n_m = int(
            session.scalar(select(func.count()).select_from(PersonalMission).where(PersonalMission.user_id == uid)) or 0
        )
    ob = prof.get("onboarding") or {}
    return {
        "ok": True,
        "plan": plan,
        "product_profile": prof,
        "hints": {
            "has_expenses": n_exp > 0,
            "has_missions": n_m > 0,
            "onboarding_complete": bool(ob.get("insights_done")),
            "wow_pending": not bool(prof.get("wow_shown")),
        },
    }
