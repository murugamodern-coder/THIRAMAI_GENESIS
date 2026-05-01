"""Tests for :mod:`services.decision_router` and the persistence layer.

Covers:

* sync routing decisions (legacy / policy / fallback);
* env-var clamping and bucketing;
* atomic round-trip of bandit weights via
  :class:`services.policy_engine_persistence.PolicyStatePersistence`;
* idempotent auto-save hook.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from services.decision_router import (
    DecisionRouter,
    reset_decision_router,
)
from services.policy_engine import (
    PolicyEngine,
    reset_policy_engine,
)
from services.policy_engine_persistence import (
    PolicyStatePersistence,
    reset_persistence,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_policy_engine()
    reset_decision_router()
    reset_persistence()
    yield
    reset_policy_engine()
    reset_decision_router()
    reset_persistence()


@pytest.fixture()
def fresh_engine() -> PolicyEngine:
    return PolicyEngine(n_features=20, alpha=1.0)


@pytest.fixture()
def fresh_router(fresh_engine: PolicyEngine) -> DecisionRouter:
    return DecisionRouter(policy_engine=fresh_engine)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_router_init_clamps_percentage(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("THIRAMAI_POLICY_ENGINE_PCT", "175")
    monkeypatch.setenv("THIRAMAI_DECISION_AB_TEST", "true")
    router = DecisionRouter()
    assert router.policy_pct == 100.0


def test_router_pct_zero_uses_legacy(monkeypatch: pytest.MonkeyPatch, fresh_router: DecisionRouter):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    fresh_router.ab_enabled = True
    fresh_router.policy_pct = 0.0
    assert fresh_router._should_use_policy(7) is False


def test_router_pct_full_uses_policy(fresh_router: DecisionRouter):
    fresh_router.ab_enabled = True
    fresh_router.policy_pct = 100.0
    assert fresh_router._should_use_policy(None) is True


def test_router_ab_disabled_always_uses_policy(fresh_router: DecisionRouter):
    fresh_router.ab_enabled = False
    assert fresh_router._should_use_policy(0) is True
    assert fresh_router._should_use_policy(99) is True


def test_router_routes_to_policy(fresh_router: DecisionRouter):
    fresh_router.ab_enabled = False  # 100% policy
    decision, engine_used = fresh_router.route(
        context={
            "intent": "analyze_trade_opportunity",
            "domain": "trading",
            "symbol": "TCS",
        },
        available_actions=["buy", "hold", "sell"],
        user_id=1,
    )
    assert engine_used == "policy_engine"
    assert decision["engine"] == "policy_engine"
    assert decision["action"] in {"buy", "hold", "sell"}
    assert 0.0 <= decision["confidence"] <= 1.0
    # Round-trip context for record_decision_outcome
    assert decision["intent"] == "analyze_trade_opportunity"
    assert decision["domain"] == "trading"


def test_router_falls_back_to_legacy_on_policy_failure(
    fresh_router: DecisionRouter, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    fresh_router.ab_enabled = False  # would normally use policy
    monkeypatch.setattr(
        fresh_router.policy_engine,
        "decide",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    decision, engine_used = fresh_router.route(
        context={"intent": "analyze_trade_opportunity", "domain": "trading"},
        user_id=1,
    )
    assert engine_used == "policy_engine"  # caller-visible label
    assert decision["engine"] == "legacy"  # actual route taken after fallback
    assert decision["action"] == "noop"


def test_router_legacy_unavailable_returns_unified_shape(
    fresh_router: DecisionRouter, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    fresh_router.ab_enabled = True
    fresh_router.policy_pct = 0.0
    decision, engine_used = fresh_router.route(
        context={
            "intent": "reorder_stock",
            "domain": "business",
            "user_message": "stock low",
        },
        user_id=1,
    )
    assert engine_used == "legacy"
    assert decision["engine"] == "legacy"
    assert decision["action"] == "noop"
    assert decision["confidence"] == 0.0
    assert "reasoning" in decision and decision["reasoning"]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _seed_one_arm(engine: PolicyEngine, action: str = "buy") -> np.ndarray:
    features = np.zeros(engine.bandit.n_features, dtype=float)
    features[0] = 1.0
    engine.bandit.update(action, features, reward=0.7)
    engine.bandit.update(action, features, reward=0.3)
    return features


def _make_persistence(tmp_path: Path) -> PolicyStatePersistence:
    return PolicyStatePersistence(storage_dir=tmp_path / "policy_state", keep=3)


def test_persistence_round_trip(tmp_path: Path, fresh_engine: PolicyEngine):
    persistence = _make_persistence(tmp_path)
    _seed_one_arm(fresh_engine, "buy")

    assert persistence.save_state(fresh_engine) is True
    assert persistence.weights_file.exists()

    fresh_engine.bandit.actions.clear()
    assert persistence.load_state(fresh_engine) is True
    assert "buy" in fresh_engine.bandit.actions
    assert fresh_engine.bandit.actions["buy"]["count"] == 2


def test_persistence_load_rejects_n_features_mismatch(
    tmp_path: Path, fresh_engine: PolicyEngine
):
    persistence = _make_persistence(tmp_path)
    _seed_one_arm(fresh_engine, "buy")
    assert persistence.save_state(fresh_engine) is True

    smaller = PolicyEngine(n_features=10, alpha=1.0)
    persistence_small = PolicyStatePersistence(
        storage_dir=persistence.storage_dir, keep=3
    )
    assert persistence_small.load_state(smaller) is False
    assert smaller.bandit.actions == {}


def test_persistence_backup_rotation(tmp_path: Path, fresh_engine: PolicyEngine):
    persistence = _make_persistence(tmp_path)  # keep=3
    _seed_one_arm(fresh_engine, "buy")

    for _ in range(6):
        assert persistence.save_state(fresh_engine) is True

    backups = sorted(persistence.backup_dir.glob("bandit_weights_*.joblib"))
    assert len(backups) <= 3


def test_persistence_auto_save_hook_idempotent(
    tmp_path: Path, fresh_engine: PolicyEngine
):
    persistence = _make_persistence(tmp_path)
    first = persistence.auto_save_hook(fresh_engine, every_n_decisions=2)
    second = persistence.auto_save_hook(fresh_engine, every_n_decisions=2)
    assert first is not None
    assert second is None  # already wrapped


def test_persistence_auto_save_triggers_on_threshold(
    tmp_path: Path, fresh_engine: PolicyEngine
):
    persistence = _make_persistence(tmp_path)
    persistence.auto_save_hook(fresh_engine, every_n_decisions=2)

    from services.policy_engine import DecisionContext

    ctx = DecisionContext(
        intent="analyze_trade_opportunity",
        domain="trading",
        organization_id=None,
    )
    decision = fresh_engine.decide(ctx, available_actions=["buy", "hold", "sell"])
    fresh_engine.update_from_outcome(ctx, decision.action, {"profit": 100}, 0.5)
    assert not persistence.weights_file.exists()  # 1st call: 1 % 2 != 0
    decision2 = fresh_engine.decide(ctx, available_actions=["buy", "hold", "sell"])
    fresh_engine.update_from_outcome(ctx, decision2.action, {"profit": 50}, 0.3)
    assert persistence.weights_file.exists()  # 2nd call triggers save


# ---------------------------------------------------------------------------
# Metrics module sanity
# ---------------------------------------------------------------------------


def test_metrics_module_imports_and_exposes_no_op_safe_api():
    from services.observability import decision_metrics as dm

    # All public functions must be callable and not raise even with bogus args.
    dm.track_decision_route("policy_engine")
    dm.track_decision_action("legacy", "noop")
    dm.track_decision_confidence(0.5, engine="policy_engine")
    dm.track_decision_reward(0.0, engine="policy_engine", action="hold")
    dm.track_exploration_bonus(0.1)
    dm.track_bandit_state({"buy": {"count": 3}})


def test_record_decision_outcome_updates_bandit(fresh_engine: PolicyEngine):
    from services.observability.decision_metrics import record_decision_outcome
    from services.policy_engine import DecisionContext

    # Inject the fresh engine as the singleton so record_decision_outcome
    # finds it via get_policy_engine().
    import services.policy_engine as pe_mod

    pe_mod._policy_engine = fresh_engine  # type: ignore[attr-defined]

    ctx = DecisionContext(
        intent="analyze_trade_opportunity", domain="trading", organization_id=None
    )
    decision_output = fresh_engine.decide(
        ctx, available_actions=["buy", "hold", "sell"]
    )
    pre_count = int(fresh_engine.bandit.actions[decision_output.action]["count"])

    record_decision_outcome(
        decision={
            "engine": "policy_engine",
            "action": decision_output.action,
            "intent": "analyze_trade_opportunity",
            "domain": "trading",
            "organization_id": None,
        },
        outcome={"profit": 1},
        reward=0.5,
    )
    post_count = int(fresh_engine.bandit.actions[decision_output.action]["count"])
    assert post_count == pre_count + 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
