"""
Bridge from HTTP / workers to the multi-agent **AI business cycle** (revenue, decisions, planner, etc.).

Uses ``core.multi_agent_cycle.execute_multi_agent_cycle`` which composes:
``revenue_engine``, ``business_decision_engine``, ``decision_prioritizer``, ``action_planner``,
and worker dispatch. Execution of risky intents remains gated by ``auto_mode`` and allow-lists
(see ``core.autonomous_loop`` for the observe/act safety model).
"""

from __future__ import annotations

from typing import Any

from core.multi_agent_cycle import execute_multi_agent_cycle


def ai_business_cycle(context: dict[str, Any]) -> dict[str, Any]:
    """Run one full AI ERP / business cycle for the given context (org, user, flags)."""
    return execute_multi_agent_cycle(dict(context))
