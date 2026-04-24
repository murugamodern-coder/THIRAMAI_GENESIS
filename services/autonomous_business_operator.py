"""
Autonomous business operator: env-gated periodic ``/operator/mega-tick``-equivalent runs.

Enable with ``THIRAMAI_AUTONOMOUS_BUSINESS_OPERATOR=1`` (requires the main asyncio scheduler
from ``THIRAMAI_SCHEDULER_AUTONOMOUS`` / background agent path). Interval default: 240s (4 min).

Staggered workload:
  * every tick: continuous loop + environment scan + adaptive autonomy
  * deal intelligence: every N ticks (default 3, ~12–15 min at 4 min)
  * strategy evolution: every M ticks (default 8, ~32 min at 4 min)
"""

from __future__ import annotations

import logging
import os
from typing import Any

_log = logging.getLogger("thiramai.autonomous_business_operator")


def is_enabled() -> bool:
    return (os.getenv("THIRAMAI_AUTONOMOUS_BUSINESS_OPERATOR") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def mega_tick_interval_seconds() -> int:
    raw = (os.getenv("THIRAMAI_OPERATOR_MEGA_TICK_SECONDS") or "240").strip()
    try:
        s = int(raw)
    except ValueError:
        s = 240
    return max(180, min(600, s))


def deal_evolve_every_n_ticks() -> int:
    raw = (os.getenv("THIRAMAI_OPERATOR_DEAL_EVOLVE_EVERY") or "3").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 3
    return max(1, min(24, n))


def strategy_evolution_every_n_ticks() -> int:
    raw = (os.getenv("THIRAMAI_OPERATOR_STRATEGY_EVERY") or "8").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 8
    return max(1, min(48, n))


def get_business_operator_policy() -> dict[str, Any]:
    return {
        "verify_outcomes": True,
        "critical_tasks_use_external_closure": True,
        "escalate_when": [
            "repeated_failures",
            "high_risk_operations",
        ],
        "continuous": [
            "learn_from_outcomes",
            "improve_strategies",
            "adapt_to_environment_changes",
        ],
        "interval_seconds": mega_tick_interval_seconds(),
        "deal_evolve_every_ticks": deal_evolve_every_n_ticks(),
        "strategy_evolution_every_ticks": strategy_evolution_every_n_ticks(),
        "scheduler_env": "THIRAMAI_AUTONOMOUS_BUSINESS_OPERATOR",
    }


def run_business_operator_tick_batch(tick_index: int) -> dict[str, Any]:
    """Run one mega-tick for every active user/org pair (sync; called from asyncio thread)."""
    from services.scheduler import distinct_active_user_org_pairs_sync

    from services.full_autonomous_operator_mode import (
        ensure_operator_threshold_defaults,
        note_predicted_risk_for_operator,
        run_operator_mega_tick,
    )

    de = deal_evolve_every_n_ticks()
    st = strategy_evolution_every_n_ticks()
    with_deal = tick_index % de == 0
    with_strategy = tick_index % st == 0
    pairs = distinct_active_user_org_pairs_sync(200)
    results: list[dict[str, Any]] = []
    for uid, oid in pairs:
        try:
            ensure_operator_threshold_defaults(int(uid))
            out = run_operator_mega_tick(
                int(uid),
                int(oid),
                with_strategy=with_strategy,
                with_deal_evolve=with_deal,
            )
            risk = note_predicted_risk_for_operator(int(uid))
            results.append(
                {
                    "user_id": int(uid),
                    "organization_id": int(oid),
                    "ok": bool(out.get("ok")),
                    "with_deal_evolve": with_deal,
                    "with_strategy": with_strategy,
                    "risk": risk.get("risk_level"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("business_operator tick user=%s org=%s: %s", uid, oid, exc)
            results.append(
                {
                    "user_id": int(uid),
                    "organization_id": int(oid),
                    "ok": False,
                    "error": str(exc)[:200],
                }
            )
    return {
        "ok": True,
        "tick": int(tick_index),
        "with_deal_evolve": with_deal,
        "with_strategy": with_strategy,
        "pairs": len(pairs),
        "results": results,
    }
