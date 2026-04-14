"""
SaaS plan matrix: feature gating + org plan resolution.

Plans on ``organizations.plan``: free | pro | business (legacy ``enterprise`` treated as business for features).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import Organization
from services.org_service import normalize_plan

FEATURE_MATRIX: dict[str, dict[str, bool]] = {
    "free": {
        "deep_research": False,
        "auto_accounting": False,
        "advanced_ai": False,
    },
    "pro": {
        "deep_research": True,
        "auto_accounting": True,
        "advanced_ai": True,
    },
    "business": {
        "deep_research": True,
        "auto_accounting": True,
        "advanced_ai": True,
    },
    "enterprise": {
        "deep_research": True,
        "auto_accounting": True,
        "advanced_ai": True,
    },
}


def effective_tier(raw_plan: str | None) -> str:
    p = normalize_plan(raw_plan)
    if p == "enterprise":
        return "business"
    return p


def plan_allows(raw_plan: str | None, feature: str) -> bool:
    tier = effective_tier(raw_plan)
    row = FEATURE_MATRIX.get(tier) or FEATURE_MATRIX["free"]
    return bool(row.get(feature, False))


def organization_plan_sync(organization_id: int) -> str:
    oid = int(organization_id)
    if oid <= 0:
        return "free"
    factory = get_session_factory()
    if factory is None:
        return "free"
    with factory() as session:
        return organization_plan_from_session(session, oid)


def organization_plan_from_session(session: Session, organization_id: int) -> str:
    org = session.get(Organization, int(organization_id))
    if org is None:
        return "free"
    return normalize_plan(getattr(org, "plan", None))


def static_plans_catalog() -> list[dict[str, Any]]:
    """Marketing + UI copy (not billing provider prices)."""
    return [
        {
            "id": "free",
            "name": "Free",
            "price_inr_month": 0,
            "tagline": "Start solo — command center + safe AI chat.",
            "features": [
                "Today brief & personal OS",
                "Business dashboard (read-mostly)",
                "AI chat (no agent tools on Free)",
                "Limited AI credits / day",
            ],
        },
        {
            "id": "pro",
            "name": "Pro",
            "price_inr_month": 1999,
            "tagline": "Run daily ops with Jarvis + automation.",
            "features": [
                "Everything in Free",
                "Jarvis agent (tool calling)",
                "Deep research & DPR drafts",
                "Auto-accounting (receipts, bank import)",
                "Higher AI limits",
            ],
        },
        {
            "id": "business",
            "name": "Business",
            "price_inr_month": 4999,
            "tagline": "Teams + scale + priority intelligence.",
            "features": [
                "Everything in Pro",
                "Highest AI limits",
                "Priority roadmap (invoice you later)",
            ],
        },
    ]
