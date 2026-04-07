"""
Optional PostgreSQL session variables for row-level security (RLS).

Application code already scopes queries with ``organization_id`` from the JWT. DB-level RLS is **opt-in**:
apply ``db/phase5_rls_optional.sql`` and call ``set_tenant_guc`` at the start of each request transaction
when ``THIRAMAI_PG_TENANT_GUC=1`` (advanced deployments only).
"""

from __future__ import annotations

import os
from sqlalchemy import text
from sqlalchemy.orm import Session


def tenant_guc_enabled() -> bool:
    return (os.getenv("THIRAMAI_PG_TENANT_GUC") or "").strip().lower() in ("1", "true", "yes", "on")


def set_tenant_guc(session: Session, organization_id: int | None) -> None:
    """
    Set ``app.current_org_id`` for the current transaction (PostgreSQL only).

    Pair with RLS policies in ``db/phase5_rls_optional.sql``. No-op on SQLite or when disabled.
    """
    if not tenant_guc_enabled():
        return
    bind = session.get_bind()
    if bind is None or getattr(bind.dialect, "name", None) != "postgresql":
        return
    if organization_id is None:
        session.execute(text("RESET app.current_org_id"))
    else:
        session.execute(text("SET LOCAL app.current_org_id = :v"), {"v": str(int(organization_id))})


def clear_tenant_guc(session: Session) -> None:
    """Remove tenant GUC (if set)."""
    set_tenant_guc(session, None)
