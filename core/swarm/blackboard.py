"""
Shared blackboard (LangGraph state) for the multi-agent orchestrator swarm.

All agents read/write the same ``SwarmState`` dict; node functions return partial updates
(LangGraph merges into state).
"""

from __future__ import annotations

from typing import TypedDict


class SwarmState(TypedDict, total=False):
    """Blackboard: single source of truth for Architect → Dev → Security → Reviewer loop."""

    # --- inputs (set before invoke) ---
    user_message: str
    organization_id: int
    request_id: str
    user_role_level: int
    billing_paused: bool
    actor_role_name: str | None
    max_retries: int

    # --- Architect ---
    plan_markdown: str
    sub_goals: list[str]

    # --- Dev ---
    dev_markdown: str
    proposed_tool_ids: list[str]

    # --- Security (Stage 3 policy engine) ---
    security_report: str
    security_hard_block: bool

    # --- Reviewer ---
    reviewer_pass: bool
    reviewer_feedback: str

    # --- control ---
    retry_count: int

    # --- output ---
    swarm_notes: str
