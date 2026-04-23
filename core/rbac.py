"""
Role-based access control — named permissions mapped to seeded roles.

Use with ``api.dependencies.require_permission(...)`` for enforcement beyond numeric
``role.level`` (which remains the source of truth for hierarchy in ``require_roles``).

Permissions are dot-separated strings (resource.action), stable for API docs and audits.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache


class Permission(str, Enum):
    """Canonical permission identifiers (store/compare as .value)."""

    # Human-in-the-loop / high-risk execution
    HITL_APPROVE = "hitl.approve"
    HITL_VIEW = "hitl.view"

    # Billing & invoices
    BILLING_MANAGE = "billing.manage"
    BILLING_INVOICE_CREATE = "billing.invoice.create"

    # Inventory
    INVENTORY_READ = "inventory.read"
    INVENTORY_WRITE = "inventory.write"

    # Production / factory
    PRODUCTION_READ = "production.read"
    PRODUCTION_WRITE = "production.write"

    # AI / orchestration
    AI_QUERY = "ai.query"
    AI_ADMIN = "ai.admin"

    # Dashboard & analytics (read-only operational views)
    DASHBOARD_READ = "dashboard.read"

    # System / tenant admin
    TENANT_ADMIN = "tenant.admin"

    # Product-level capabilities (cross-domain)
    VIEW_PERSONAL = "view_personal"
    MANAGE_BUSINESS = "manage_business"
    TRADE_STOCK = "trade_stock"
    RUN_RESEARCH = "run_research"
    BUILD_APPS = "build_apps"


# Full access for platform / tenant owners
_ALL = frozenset(p.value for p in Permission)

_MANAGER = frozenset(
    {
        Permission.HITL_APPROVE.value,
        Permission.HITL_VIEW.value,
        Permission.BILLING_MANAGE.value,
        Permission.BILLING_INVOICE_CREATE.value,
        Permission.INVENTORY_READ.value,
        Permission.INVENTORY_WRITE.value,
        Permission.PRODUCTION_READ.value,
        Permission.PRODUCTION_WRITE.value,
        Permission.AI_QUERY.value,
        Permission.DASHBOARD_READ.value,
        Permission.VIEW_PERSONAL.value,
        Permission.MANAGE_BUSINESS.value,
        Permission.RUN_RESEARCH.value,
        Permission.BUILD_APPS.value,
    }
)

_SUPERVISOR = frozenset(
    {
        Permission.INVENTORY_READ.value,
        Permission.INVENTORY_WRITE.value,
        Permission.PRODUCTION_READ.value,
        Permission.PRODUCTION_WRITE.value,
        Permission.DASHBOARD_READ.value,
        Permission.AI_QUERY.value,
        Permission.VIEW_PERSONAL.value,
        Permission.RUN_RESEARCH.value,
    }
)

_WORKER = frozenset(
    {
        Permission.INVENTORY_READ.value,
        Permission.PRODUCTION_READ.value,
        Permission.DASHBOARD_READ.value,
        Permission.AI_QUERY.value,
        Permission.VIEW_PERSONAL.value,
    }
)

_CUSTOMER = frozenset(
    {
        Permission.DASHBOARD_READ.value,
        Permission.VIEW_PERSONAL.value,
    }
)


@lru_cache(maxsize=32)
def permissions_for_role(role_name: str) -> frozenset[str]:
    """
    Return the permission set for a role name (case-insensitive).

    Unknown roles receive **no** permissions (fail-closed); map new roles in provisioning.
    """
    key = (role_name or "").strip().lower()
    if key in ("superadmin", "owner", "admin"):
        return _ALL
    if key == "manager":
        return _MANAGER
    if key == "supervisor":
        return _SUPERVISOR
    if key in ("worker", "staff"):
        return _WORKER
    if key == "customer":
        return _CUSTOMER
    return frozenset()


def user_has_permission(*, role_name: str, permission: str) -> bool:
    """True if ``permission`` is granted to ``role_name``."""
    perm = (permission or "").strip()
    if not perm:
        return False
    return perm in permissions_for_role(role_name)
