"""Persist generated static-site metadata (Part E)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import GeneratedWebsite

_log = logging.getLogger("thiramai.website_db")


def _factory() -> sessionmaker[Session] | None:
    return get_session_factory()  # type: ignore[return-value]


def upsert_generated_website_sync(
    *,
    organization_id: int,
    slug: str,
    template_type: str,
    public_url: str,
    disk_path: str,
) -> dict[str, Any]:
    oid = int(organization_id)
    fac = _factory()
    if fac is None:
        return {"ok": False, "error": "database not configured"}
    slug_s = (slug or "").strip().lower()[:80]
    with fac() as session:
        with session.begin():
            row = session.execute(
                select(GeneratedWebsite).where(GeneratedWebsite.organization_id == oid).limit(1)
            ).scalar_one_or_none()
            if row:
                row.slug = slug_s
                row.template_type = (template_type or "shop")[:32]
                row.public_url = (public_url or "")[:512]
                row.disk_path = (disk_path or "")[:1024]
                row.updated_at = datetime.now(timezone.utc)
            else:
                session.add(
                    GeneratedWebsite(
                        organization_id=oid,
                        slug=slug_s,
                        template_type=(template_type or "shop")[:32],
                        public_url=(public_url or "")[:512],
                        disk_path=(disk_path or "")[:1024],
                    )
                )
    return {"ok": True, "organization_id": oid, "slug": slug_s}


def get_generated_website_sync(organization_id: int) -> dict[str, Any]:
    oid = int(organization_id)
    fac = _factory()
    if fac is None:
        return {"ok": False, "error": "database not configured"}
    with fac() as session:
        row = session.execute(select(GeneratedWebsite).where(GeneratedWebsite.organization_id == oid).limit(1)).scalar_one_or_none()
    if row is None:
        return {"ok": False, "error": "not found"}
    return {
        "ok": True,
        "organization_id": oid,
        "slug": row.slug,
        "template_type": row.template_type,
        "public_url": row.public_url,
        "disk_path": row.disk_path,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
