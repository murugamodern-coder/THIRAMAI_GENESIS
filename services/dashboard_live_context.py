"""
Safe **live dashboard** context: ``corporate_identity`` is always a well-shaped dict for Jinja + JSON.

Falls back to operator defaults when economics/DB fetch raises or returns a non-dict, so
``GET /dashboard/live`` never fails on missing template variables.
"""

from __future__ import annotations

import os
from typing import Any

_FALLBACK_NAME = "Modern Corporation"
_FALLBACK_GST = "33BTHPM0629L3ZJ"


def default_dashboard_org_id() -> int:
    for key in (
        "THIRAMAI_CORPORATE_DASHBOARD_ORG_ID",
        "THIRAMAI_DEFAULT_ORG_ID",
        "THIRAMAI_DEV_ORG_ID",
        "THIRAMAI_AUTOSCALE_BUDGET_ORG_ID",
    ):
        raw = (os.getenv(key) or "").strip()
        if raw.isdigit():
            return int(raw)
    return 1


def effective_dashboard_org_id() -> int:
    """
    When the configured default is ``1`` (no explicit org env):

    * Prefer the organization whose trimmed name equals **Modern Corporation** (case-insensitive),
      lowest ``id`` if several match.
    * Else if ``organizations.id=1`` exists **and** has a non-empty name, use ``1``.
    * Else prefer the **lowest id** whose ``name`` is non-empty.
    * Else fall back to the lowest id overall.

    Explicit ``THIRAMAI_CORPORATE_DASHBOARD_ORG_ID`` / related env ids are never remapped.
    """
    wanted = default_dashboard_org_id()
    if wanted != 1:
        return wanted
    try:
        from sqlalchemy import func, select

        from core.database import get_session_factory
        from core.db.models import Organization

        factory = get_session_factory()
        if factory is None:
            return wanted
        _mc = "modern corporation"
        with factory() as session:
            mc_id = session.execute(
                select(Organization.id)
                .where(func.lower(func.trim(Organization.name)) == _mc)
                .order_by(Organization.id.asc())
                .limit(1)
            ).scalar_one_or_none()
            if mc_id is not None:
                return int(mc_id)
            rows = session.execute(
                select(Organization.id, Organization.name).order_by(Organization.id.asc())
            ).all()
            if not rows:
                return 1
            o1 = session.get(Organization, 1)
            if o1 is not None and (o1.name or "").strip():
                return 1
            for rid, rname in rows:
                if (rname or "").strip():
                    return int(rid)
            return int(rows[0][0])
    except Exception:
        pass
    return 1


def _fallback_corporate_identity(*, organization_id: int) -> dict[str, Any]:
    """Used only when DB/economics fetch fails — explicit safe defaults (product request)."""
    return {
        "organization_id": int(organization_id),
        "name": _FALLBACK_NAME,
        "company_name": _FALLBACK_NAME,
        "gst_number": _FALLBACK_GST,
    }


def safe_corporate_identity_for_live_dashboard() -> dict[str, Any]:
    """
    Always returns a dict with ``organization_id``, ``name``, ``company_name``, ``gst_number``.

    On success, ``name`` mirrors ``company_name``. On any error, returns fallback Modern Corporation + GST.
    """
    oid = effective_dashboard_org_id()
    try:
        from services.economics_service import get_corporate_economics_context

        raw = get_corporate_economics_context(oid)
        if raw is None or not isinstance(raw, dict):
            return _fallback_corporate_identity(organization_id=default_dashboard_org_id())
    except Exception:
        return _fallback_corporate_identity(organization_id=default_dashboard_org_id())

    cn = (raw.get("company_name") or raw.get("name") or "").strip()
    gst_val = raw.get("gst_number")
    gst = (gst_val or "").strip() if gst_val is not None else ""
    org_out = int(raw.get("organization_id") or oid)
    return {
        "organization_id": org_out,
        "company_name": cn,
        "name": cn,
        "gst_number": gst or None,
    }


def assert_corporate_identity_template_integrity(snap: dict[str, Any] | None) -> tuple[bool, str]:
    """SRE: required keys for ``dashboard.html`` + ``state.json`` consumers."""
    if not isinstance(snap, dict):
        return False, "corporate_identity_not_a_dict"
    for k in ("organization_id", "company_name", "name", "gst_number"):
        if k not in snap:
            return False, f"missing_key:{k}"
    return True, "ok"
