"""
Upgrade 2.1 — Event-driven hooks (stubs / call sites for websocket or DB triggers).

Call these from inventory, meetings, or other writers when polling is not enough.
Full WebSocket wiring can subscribe to the same helpers later.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("thiramai.jarvis_proactive_events")


def notify_low_stock_for_org(*, user_id: int, organization_id: int, sku: str, quantity: Any = None) -> None:
    """
    Stock threshold crossed — enqueue a focused proactive refresh for one user/org.

    Safe no-op if dependencies missing; does not block the caller.
    """
    uid = int(user_id)
    oid = int(organization_id)
    if uid <= 0 or oid <= 0 or not (sku or "").strip():
        return
    try:
        from services.jarvis_proactive_service import generate_morning_intelligence_sync

        generate_morning_intelligence_sync(user_id=uid, organization_ids=[oid])
    except Exception as exc:
        _log.debug("notify_low_stock_for_org skipped: %s", exc)


def notify_meeting_window(*, user_id: int, organization_ids: list[int]) -> None:
    """Timer / calendar hook: run realtime meeting scan for one user."""
    uid = int(user_id)
    oids = [int(x) for x in organization_ids if int(x) > 0]
    if uid <= 0 or not oids:
        return
    try:
        from services.jarvis_proactive_service import run_realtime_intelligence_sync

        run_realtime_intelligence_sync(user_id=uid, organization_ids=oids[:8])
    except Exception as exc:
        _log.debug("notify_meeting_window skipped: %s", exc)
