"""Autonomous operations engine for daily business cycles across organizations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.continuous_thinking_loop_engine import run_continuous_thinking_cycle
from services.money_loop_engine import run_money_loop_cycle
from services.multi_org_control_engine import list_user_organizations
from services.revenue_engine import auto_reinvest_profit, revenue_snapshot
from services.strategy_generator_engine import generate_and_promote


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_daily_business_cycle(user_id: int, organization_id: int) -> dict[str, Any]:
    think = run_continuous_thinking_cycle(int(user_id), int(organization_id))
    money = run_money_loop_cycle(int(user_id), int(organization_id), "owner")
    strategy = generate_and_promote(int(user_id), int(organization_id))
    revenue = revenue_snapshot(int(user_id), 24 * 7)
    reinvest = auto_reinvest_profit(int(user_id), int(organization_id), 0.5)
    return {
        "ok": True,
        "organization_id": int(organization_id),
        "executed_at": _now_iso(),
        "continuous_thinking": think,
        "money_loop": money,
        "strategy_generation": strategy,
        "revenue_snapshot": revenue,
        "reinvestment": reinvest,
    }


def run_multi_org_daily_cycles(user_id: int) -> dict[str, Any]:
    orgs = list_user_organizations(int(user_id))
    results = []
    for org in orgs:
        oid = int(org.get("organization_id") or 0)
        if oid <= 0 or bool(org.get("is_disabled")):
            continue
        results.append(run_daily_business_cycle(int(user_id), oid))
    return {"ok": True, "user_id": int(user_id), "executed_at": _now_iso(), "cycles": results}
