"""Orchestrator swarm: routing and graph compile (no live Groq)."""

from __future__ import annotations

from core.swarm.graph import build_swarm_graph
from core.swarm.nodes import route_after_reviewer
from core.swarm.pipeline import augment_shared_core_with_swarm, orchestrator_swarm_enabled


def test_route_after_reviewer_pass():
    assert route_after_reviewer({"reviewer_pass": True}) == "merge"


def test_route_after_reviewer_retry():
    assert (
        route_after_reviewer(
            {
                "reviewer_pass": False,
                "retry_count": 0,
                "max_retries": 2,
                "security_hard_block": False,
            }
        )
        == "retry"
    )


def test_route_after_reviewer_max_retries_merge():
    assert (
        route_after_reviewer(
            {
                "reviewer_pass": False,
                "retry_count": 2,
                "max_retries": 2,
                "security_hard_block": False,
            }
        )
        == "merge"
    )


def test_route_security_hard_second_round_merge():
    assert (
        route_after_reviewer(
            {
                "reviewer_pass": False,
                "retry_count": 1,
                "max_retries": 5,
                "security_hard_block": True,
            }
        )
        == "merge"
    )


def test_build_swarm_graph_compiles():
    g = build_swarm_graph()
    app = g.compile()
    assert app is not None


def test_augment_disabled_noop(monkeypatch):
    monkeypatch.delenv("THIRAMAI_ORCHESTRATOR_SWARM", raising=False)
    assert orchestrator_swarm_enabled() is False
    out = augment_shared_core_with_swarm(
        "BASE",
        user_message="hi",
        organization_id=1,
        request_id="r1",
        user_role_level=1,
        billing_paused=False,
    )
    assert out == "BASE"
