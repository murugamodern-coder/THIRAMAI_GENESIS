"""LangGraph StateGraph wiring: Architect → Dev → Security → Reviewer → (retry | merge)."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from core.swarm.blackboard import SwarmState
from core.swarm.nodes import (
    node_architect,
    node_bump_retry,
    node_dev,
    node_merge,
    node_reviewer,
    node_security,
    route_after_reviewer,
)

_compiled = None


def build_swarm_graph() -> StateGraph:
    g = StateGraph(SwarmState)
    g.add_node("architect", node_architect)
    g.add_node("dev", node_dev)
    g.add_node("security", node_security)
    g.add_node("reviewer", node_reviewer)
    g.add_node("merge", node_merge)
    g.add_node("bump_retry", node_bump_retry)
    g.add_edge(START, "architect")
    g.add_edge("architect", "dev")
    g.add_edge("dev", "security")
    g.add_edge("security", "reviewer")
    g.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        {"merge": "merge", "retry": "bump_retry"},
    )
    g.add_edge("bump_retry", "dev")
    g.add_edge("merge", END)
    return g


def get_compiled_swarm():
    global _compiled
    if _compiled is None:
        _compiled = build_swarm_graph().compile()
    return _compiled


def run_swarm(initial: SwarmState, *, recursion_limit: int = 32) -> SwarmState:
    app = get_compiled_swarm()
    return app.invoke(dict(initial), config={"recursion_limit": recursion_limit})
