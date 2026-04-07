"""
Inventory risk signals for the Command Center (thin wrapper over dashboard low-stock queries).
"""

from __future__ import annotations

from typing import Any

from services.analytics_service import list_low_stock_alerts_sync


def get_inventory_alerts(
    organization_id: int,
    *,
    threshold: int = 5,
    limit: int = 200,
) -> dict[str, Any]:
    """Low-quantity rows for ``organization_id`` (same shape as ``list_low_stock_alerts_sync``)."""
    return list_low_stock_alerts_sync(int(organization_id), threshold=int(threshold), limit=limit)
