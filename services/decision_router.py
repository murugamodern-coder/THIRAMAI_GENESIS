"""
Synchronous decision router for the PolicyEngine ↔ legacy A/B rollout.

This is the **sync** counterpart to :mod:`services.decision_brain_v2`. Use:

* :class:`DecisionBrainV2` (async) inside FastAPI request handlers and other
  async code paths;
* :class:`DecisionRouter` (sync) inside CLI, schedulers, and worker code that
  is not async.

Both share the same :class:`services.policy_engine.PolicyEngine` singleton, so
bandit weights and persisted ``LearningLog`` rows are unified across the two
entry points. Routing also reads the same env vars
(``THIRAMAI_DECISION_AB_TEST`` / ``THIRAMAI_POLICY_ENGINE_PCT`` plus the bare
``DECISION_AB_TEST`` / ``POLICY_ENGINE_PCT`` aliases), so flipping the A/B
percentage moves both surfaces together.

Unlike the original spec, this router:

* preserves the unified decision shape (``action``, ``action_type``,
  ``confidence``, ``reasoning``, ``expected_reward``, ``engine``,
  ``timestamp``, plus pass-through context for outcome reconstruction);
* maps legacy ``priority`` → ``confidence`` instead of pulling a non-existent
  ``confidence`` field off the legacy result;
* writes a ``LearningLog`` row tagged ``source_type='legacy_brain'`` so the
  A/B comparison in :mod:`services.observability.ab_test_metrics` actually has
  legacy data to compare against; and
* emits Prometheus metrics through
  :mod:`services.observability.decision_metrics` (no-op if the dep is absent).
"""

from __future__ import annotations

import logging
import os
import random
import threading
from datetime import datetime, timezone
from typing import Any, Mapping

from services.decision_brain import run_decision_engine_sync
from services.decision_brain_v2 import _legacy_log_decision
from services.observability.decision_metrics import (
    track_bandit_state,
    track_decision_action,
    track_decision_confidence,
    track_decision_latency,
    track_decision_route,
    track_exploration_bonus,
)
from services.policy_engine import DecisionContext, PolicyEngine, get_policy_engine

logger = logging.getLogger(__name__)


_PRIORITY_TO_CONFIDENCE: dict[str, float] = {"high": 0.8, "medium": 0.55, "low": 0.3}


def _bool_env(*names: str, default: bool) -> bool:
    for name in names:
        raw = (os.getenv(name) or "").strip().lower()
        if raw:
            return raw in ("1", "true", "yes", "on")
    return default


def _float_env(*names: str, default: float) -> float:
    for name in names:
        raw = (os.getenv(name) or "").strip()
        if raw:
            try:
                return float(raw)
            except ValueError:
                continue
    return default


_STRATEGIC_HORIZONS = frozenset({"strategic", "tactical"})


class DecisionRouter:
    """Synchronous A/B router between PolicyEngine and the legacy brain.

    A third route - the 3-layer hierarchical policy - is gated behind the
    ``THIRAMAI_HIERARCHICAL_POLICY`` env flag. When the flag is on AND the
    inbound request specifies ``horizon`` (or ``time_horizon``) of
    ``"strategic"`` / ``"tactical"``, the request is sent to the hierarchical
    planner instead of going through the existing PolicyEngine ↔ legacy A/B
    split. ``horizon="immediate"`` (the default) is unchanged - it still goes
    through the existing A/B flow, so this is a strictly additive route.
    """

    def __init__(self, *, policy_engine: PolicyEngine | None = None) -> None:
        self.policy_engine: PolicyEngine = policy_engine or get_policy_engine()
        self.ab_enabled = _bool_env(
            "THIRAMAI_DECISION_AB_TEST", "DECISION_AB_TEST", default=True
        )
        pct = _float_env(
            "THIRAMAI_POLICY_ENGINE_PCT", "POLICY_ENGINE_PCT", default=0.0
        )
        self.policy_pct = max(0.0, min(100.0, pct))
        self.use_hierarchical = _bool_env(
            "THIRAMAI_HIERARCHICAL_POLICY", "HIERARCHICAL_POLICY", default=False
        )
        logger.info(
            "DecisionRouter ready ab_enabled=%s policy_pct=%.1f hierarchical=%s",
            self.ab_enabled,
            self.policy_pct,
            self.use_hierarchical,
        )

    # -- routing decision -------------------------------------------------

    def _should_use_policy(self, user_id: int | None) -> bool:
        if not self.ab_enabled:
            return True
        if self.policy_pct <= 0:
            return False
        if self.policy_pct >= 100:
            return True
        if user_id is not None:
            return (int(user_id) % 100) < self.policy_pct
        return random.random() * 100.0 < self.policy_pct

    # -- public API -------------------------------------------------------

    def route(
        self,
        context: Mapping[str, Any],
        available_actions: list[str] | None = None,
        user_id: int | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Route a decision request and return ``(decision_dict, engine_used)``.

        ``engine_used`` is one of ``"policy_engine"`` or ``"legacy"``. When the
        policy path raises and we fall back to legacy, the returned engine is
        ``"legacy"`` and the metric ``thiramai_decision_route_total{engine="policy_engine_failed"}``
        is incremented for visibility.
        """

        ctx = dict(context or {})
        # Allow context["user_id"] to override the explicit arg only if the arg is None.
        effective_user_id = user_id if user_id is not None else ctx.get("user_id")

        horizon = str(ctx.get("horizon") or ctx.get("time_horizon") or "immediate").strip().lower()
        if self.use_hierarchical and horizon in _STRATEGIC_HORIZONS:
            decision = self._route_to_hierarchical(ctx, horizon, effective_user_id)
            # When the hierarchical path failed and we fell back to legacy, the
            # returned dict carries engine="legacy" - propagate that so the
            # tuple's engine label matches the truth.
            engine_label = str(decision.get("engine") or "hierarchical")
            return decision, engine_label

        if self._should_use_policy(effective_user_id):
            return self._route_to_policy(ctx, available_actions, effective_user_id), "policy_engine"
        return self._route_to_legacy(ctx, effective_user_id), "legacy"

    # -- variants ---------------------------------------------------------

    @track_decision_latency(engine="hierarchical")
    def _route_to_hierarchical(
        self,
        context: dict[str, Any],
        horizon: str,
        user_id: int | None,
    ) -> dict[str, Any]:
        """Send the request to the 3-layer hierarchical planner.

        On any unexpected failure we fall back to the legacy decision brain so
        the caller still gets a usable shape, and emit
        ``thiramai_decision_route_total{engine="hierarchical_failed"}`` for
        visibility.
        """
        ctx = dict(context)
        if user_id is not None:
            ctx.setdefault("user_id", user_id)
        try:
            from services.hierarchical_policy import get_hierarchical_policy

            decision = get_hierarchical_policy().decide(ctx, horizon=horizon)
        except Exception as exc:
            logger.warning(
                "hierarchical.decide failed: %s - falling back to legacy", exc, exc_info=True
            )
            track_decision_route("hierarchical_failed")
            return self._route_to_legacy(ctx, user_id)

        track_decision_route(f"hierarchical_{horizon}")
        action = decision.get("action")
        if isinstance(action, str) and action:
            track_decision_action("hierarchical", action)
        confidence = decision.get("confidence")
        if isinstance(confidence, (int, float)):
            track_decision_confidence(float(confidence), engine="hierarchical")
        decision.setdefault("engine", "hierarchical")
        decision.setdefault("source", "hierarchical")
        decision.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        return decision

    @track_decision_latency(engine="policy_engine")
    def _route_to_policy(
        self,
        context: dict[str, Any],
        available_actions: list[str] | None,
        user_id: int | None,
    ) -> dict[str, Any]:
        try:
            decision_context = DecisionContext(
                intent=str(context.get("intent") or "unknown"),
                domain=str(context.get("domain") or "business"),
                user_id=user_id,
                organization_id=context.get("organization_id"),
                risk_tolerance=float(context.get("risk_tolerance", 0.5)),
                time_horizon=str(context.get("time_horizon", "short")),
                constraints=dict(context.get("constraints") or {}),
                metadata=dict(context),
            )
            output = self.policy_engine.decide(
                decision_context, available_actions=available_actions
            )
        except Exception as exc:
            logger.warning(
                "PolicyEngine.decide failed: %s — falling back to legacy", exc, exc_info=True
            )
            track_decision_route("policy_engine_failed")
            return self._route_to_legacy(context, user_id)

        track_decision_route("policy_engine")
        track_decision_action("policy_engine", output.action)
        track_decision_confidence(output.confidence, engine="policy_engine")
        track_exploration_bonus(output.exploration_bonus)
        track_bandit_state(self.policy_engine.bandit.actions)

        return {
            "action": output.action,
            "action_type": output.action_type,
            "confidence": output.confidence,
            "reasoning": list(output.reasoning),
            "expected_reward": output.expected_reward,
            "exploration_bonus": output.exploration_bonus,
            "engine": "policy_engine",
            "source": "policy_engine",
            "timestamp": output.timestamp.isoformat(),
            "learning_log_id": output.learning_log_id,
            # Pass-through context so callers can reconstruct DecisionContext
            # for record_decision_outcome.
            "intent": str(context.get("intent") or "unknown"),
            "domain": str(context.get("domain") or "business"),
            "user_id": user_id,
            "organization_id": context.get("organization_id"),
            "risk_tolerance": float(context.get("risk_tolerance", 0.5)),
            "time_horizon": str(context.get("time_horizon", "short")),
            "constraints": dict(context.get("constraints") or {}),
            "metadata": dict(context),
            "context": dict(context),
        }

    @track_decision_latency(engine="legacy")
    def _route_to_legacy(
        self,
        context: dict[str, Any],
        user_id: int | None,
    ) -> dict[str, Any]:
        organization_id = context.get("organization_id")
        intent = str(context.get("intent") or "unknown")
        domain = str(context.get("domain") or "business")
        user_message = str(
            context.get("message") or context.get("user_message") or intent
        )
        try:
            raw = run_decision_engine_sync(
                user_message=user_message,
                organization_id=int(organization_id or 0),
                actor_role_name=context.get("role") or context.get("actor_role_name"),
                user_id=user_id,
                correlation_id=context.get("correlation_id"),
            )
        except Exception as exc:
            logger.error("legacy decision_brain raised: %s", exc, exc_info=True)
            raw = {"ok": False, "error": str(exc), "decision": None}

        decision_payload = raw.get("decision") if isinstance(raw, dict) else None
        if isinstance(decision_payload, dict):
            action = str(decision_payload.get("action") or "noop")
            priority = str(decision_payload.get("priority") or "low").lower()
            confidence = float(_PRIORITY_TO_CONFIDENCE.get(priority, 0.4))
            rationale = str(decision_payload.get("rationale") or "")
            reasoning = [rationale] if rationale else ["Legacy brain decision."]
        else:
            err = str((raw or {}).get("error") or "legacy_no_decision")
            action = "noop"
            confidence = 0.0
            reasoning = [f"Legacy brain unavailable: {err}"]

        action_type = self.policy_engine._classify_action(action)
        timestamp = datetime.now(timezone.utc)

        track_decision_route("legacy")
        track_decision_action("legacy", action)
        track_decision_confidence(confidence, engine="legacy")

        learning_log_id = _legacy_log_decision(
            organization_id=organization_id,
            user_id=user_id,
            intent=intent,
            domain=domain,
            action=action,
            action_type=action_type,
            confidence=confidence,
            reasoning=reasoning,
            decision_payload=decision_payload if isinstance(decision_payload, dict) else None,
            raw=raw if isinstance(raw, dict) else {},
            timestamp=timestamp,
        )

        return {
            "action": action,
            "action_type": action_type,
            "confidence": confidence,
            "reasoning": reasoning,
            "expected_reward": 0.0,
            "exploration_bonus": 0.0,
            "engine": "legacy",
            "source": "legacy_brain",
            "timestamp": timestamp.isoformat(),
            "learning_log_id": learning_log_id,
            "intent": intent,
            "domain": domain,
            "user_id": user_id,
            "organization_id": organization_id,
            "risk_tolerance": float(context.get("risk_tolerance", 0.5)),
            "time_horizon": str(context.get("time_horizon", "short")),
            "constraints": dict(context.get("constraints") or {}),
            "metadata": dict(context),
            "context": dict(context),
            "legacy_raw": {
                "ok": bool((raw or {}).get("ok")),
                "validation_error": (raw or {}).get("validation_error"),
                "safety_error": (raw or {}).get("safety_error"),
            },
        }


# ---------------------------------------------------------------------------
# Singleton + convenience function
# ---------------------------------------------------------------------------


_router: DecisionRouter | None = None
_router_lock = threading.Lock()


def get_decision_router() -> DecisionRouter:
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = DecisionRouter()
    return _router


def reset_decision_router() -> None:
    """Test-only: drop the singleton so env-flag changes can take effect.

    Also resets the hierarchical-policy singleton (when importable) so an
    env-flag flip is picked up end-to-end without leaking ``active_plan`` /
    ``active_goal`` state between tests.
    """

    global _router
    with _router_lock:
        _router = None
    try:
        from services.hierarchical_policy import reset_hierarchical_policy

        reset_hierarchical_policy()
    except Exception:  # pragma: no cover - import guarded for partial installs
        pass


def route_decision(
    context: Mapping[str, Any],
    available_actions: list[str] | None = None,
    user_id: int | None = None,
) -> tuple[dict[str, Any], str]:
    """Convenience wrapper around the singleton :class:`DecisionRouter`.

    Example::

        decision, engine = route_decision(
            context={"intent": "analyze_trade_opportunity", "symbol": "TCS",
                     "domain": "trading", "organization_id": 1},
            available_actions=["buy", "hold", "sell"],
            user_id=42,
        )
    """

    return get_decision_router().route(context, available_actions, user_id)


__all__ = [
    "DecisionRouter",
    "get_decision_router",
    "reset_decision_router",
    "route_decision",
]
