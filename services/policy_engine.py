"""
PolicyEngine — the single decision policy for Thiramai (Phase 1, Week 1).

Replaces the long tail of ``decision_*`` / ``autonomy_*`` modules with one
contextual-bandit policy on top of the existing :class:`BayesianWorldModel`.

Two distinct surfaces live here:

* The **autonomy policy loader** (``AutonomyPolicy``, ``load_autonomy_policy``,
  ``policy_allows_auto_approve``) — pre-existing API consumed by
  ``services.auto_action_engine``. Untouched.
* The **central PolicyEngine** (``PolicyEngine``, ``LinUCBBandit``,
  ``DecisionContext``, ``DecisionOutput``, ``get_policy_engine``) — new code.

Imports are wired against this repository (``core.database.get_session_factory``,
``core.db.models.LearningLog``, ``services.world_model.bayesian_world_model``)
because the original spec referenced symbols (``SessionLocal``,
``models.learning_log``, ``core.logger``) that do not exist here.
"""

from __future__ import annotations

import json
import logging
import threading
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import AutonomySetting, LearningLog

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pre-existing API: AutonomyPolicy / load_autonomy_policy / auto-approve gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AutonomyPolicy:
    auto_mode_enabled: bool
    confidence_high_threshold: float
    confidence_medium_threshold: float
    auto_approve: dict[str, Any]


DEFAULT_POLICY: dict[str, Any] = {
    "thresholds": {"high": 0.92, "medium": 0.80},
    "autoApprove": {
        # Example policy shape:
        # "reorder_stock": {"maxQuantity": 50}
    },
}


def load_autonomy_policy(*, organization_id: int) -> AutonomyPolicy:
    oid = int(organization_id)
    factory = get_session_factory()
    if factory is None:
        return AutonomyPolicy(False, 0.92, 0.80, {})
    with factory() as session:
        row = session.scalar(
            select(AutonomySetting).where(AutonomySetting.organization_id == oid).limit(1)
        )
        enabled = bool(getattr(row, "auto_mode_enabled", False)) if row is not None else False
        raw = dict(getattr(row, "policy", None) or DEFAULT_POLICY)

    thr = raw.get("thresholds") or {}
    try:
        high = float(thr.get("high", DEFAULT_POLICY["thresholds"]["high"]))
    except Exception:
        high = DEFAULT_POLICY["thresholds"]["high"]
    try:
        med = float(thr.get("medium", DEFAULT_POLICY["thresholds"]["medium"]))
    except Exception:
        med = DEFAULT_POLICY["thresholds"]["medium"]

    auto_approve = raw.get("autoApprove") or {}
    if not isinstance(auto_approve, dict):
        auto_approve = {}
    return AutonomyPolicy(
        auto_mode_enabled=enabled,
        confidence_high_threshold=max(0.0, min(1.0, high)),
        confidence_medium_threshold=max(0.0, min(1.0, med)),
        auto_approve=auto_approve,
    )


def policy_allows_auto_approve(
    *, policy: AutonomyPolicy, action: str, payload: dict[str, Any]
) -> tuple[bool, str | None]:
    rules = policy.auto_approve.get(action) if isinstance(policy.auto_approve, dict) else None
    if not isinstance(rules, dict):
        return False, "policy_no_rule"
    if "maxQuantity" in rules:
        try:
            max_q = float(rules["maxQuantity"])
            q = float(payload.get("quantity") or payload.get("qty") or 0)
            if q <= 0:
                return False, "invalid_quantity"
            if q > max_q:
                return False, "quantity_over_limit"
        except Exception:
            return False, "policy_invalid_rule"
    return True, None


# ---------------------------------------------------------------------------
# PolicyEngine: contextual bandit on top of the Bayesian world model
# ---------------------------------------------------------------------------


_TIME_HORIZON_BUCKETS = ("immediate", "short", "medium", "long")
_DOMAIN_BUCKETS = ("trading", "business", "personal", "system")

# Outcomes we read from the Bayesian world model (must exist in
# ``services.world_model.bayesian_world_model._OUTCOME_INFLUENCES``).
_WORLD_OUTCOMES = (
    "trading_drawdown_alert",
    "cash_crunch_30d",
    "inventory_stockout_7d",
    "system_decision_quality_drop",
    "revenue_up_next_week",
)


def _stable_unit_hash(text: str) -> float:
    """Map a string to ``[0.0, 1.0)`` deterministically across process restarts.

    Python's built-in ``hash()`` is salted per process by default
    (``PYTHONHASHSEED=random``) so using it for feature encoding silently
    poisons bandit weights between deploys. ``zlib.adler32`` is fast and stable.
    """

    return (zlib.adler32((text or "").encode("utf-8")) & 0xFFFFFFFF) / float(0x1_0000_0000)


def _bucket_index(value: str | None, buckets: tuple[str, ...]) -> float:
    """Map a categorical to a bucket-normalised float (unknowns → mid-point)."""

    if not value:
        return 0.5
    s = str(value).strip().lower()
    if s in buckets:
        return buckets.index(s) / max(1, len(buckets) - 1)
    return _stable_unit_hash(s)


@dataclass
class DecisionContext:
    """Structured context for a decision request."""

    intent: str
    domain: str  # "business" | "trading" | "personal" | "system"
    user_id: int | None = None
    organization_id: int | None = None
    risk_tolerance: float = 0.5  # 0.0 (averse) … 1.0 (aggressive)
    time_horizon: str = "short"  # "immediate" | "short" | "medium" | "long"
    constraints: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionOutput:
    """Structured decision output."""

    action: str
    action_type: str
    confidence: float
    expected_reward: float
    reasoning: list[str]
    context_used: dict[str, Any]
    world_state: dict[str, Any]
    timestamp: datetime
    exploration_bonus: float
    features: list[float]  # cached for faithful update_from_outcome
    learning_log_id: int | None = None


class LinUCBBandit:
    """Linear UCB contextual bandit (per-action ridge regression).

    For each action ``a`` we keep ``A_a`` (regularised feature covariance) and
    ``b_a`` (reward-weighted feature sum). The chosen action maximises
    ``θ_aᵀ x + α · √(xᵀ A_a⁻¹ x)`` (Auer 2002 / Li et al. 2010).
    """

    def __init__(self, n_features: int, alpha: float = 1.0) -> None:
        if n_features <= 0:
            raise ValueError("n_features must be positive")
        self.n_features = int(n_features)
        self.alpha = float(alpha)
        self.actions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _ensure_action(self, action: str) -> dict[str, Any]:
        rec = self.actions.get(action)
        if rec is None:
            rec = {
                "A": np.eye(self.n_features),
                "b": np.zeros(self.n_features),
                "count": 0,
            }
            self.actions[action] = rec
        return rec

    def select_action(
        self,
        available_actions: list[str],
        context_features: np.ndarray,
    ) -> tuple[str, float, float]:
        """Return ``(action, expected_reward, exploration_bonus)``."""

        if not available_actions:
            raise ValueError("available_actions is empty")
        x = np.asarray(context_features, dtype=float).reshape(-1)
        if x.shape[0] != self.n_features:
            raise ValueError(f"Expected {self.n_features} features, got {x.shape[0]}")

        best_action: str | None = None
        best_ucb = -float("inf")
        best_expected = 0.0
        best_bonus = 0.0

        with self._lock:
            for action in available_actions:
                rec = self._ensure_action(action)
                A = rec["A"]
                b = rec["b"]
                # ``solve`` is more stable than ``inv`` for small ridge matrices.
                A_inv_x = np.linalg.solve(A, x)
                theta = np.linalg.solve(A, b)
                expected_reward = float(theta @ x)
                exploration_bonus = float(self.alpha * np.sqrt(max(x @ A_inv_x, 0.0)))
                ucb = expected_reward + exploration_bonus
                if ucb > best_ucb:
                    best_ucb = ucb
                    best_action = action
                    best_expected = expected_reward
                    best_bonus = exploration_bonus

        # ``best_action`` is non-None because available_actions is non-empty.
        assert best_action is not None
        return best_action, best_expected, best_bonus

    def update(self, action: str, context_features: np.ndarray, reward: float) -> None:
        """Apply one observation to the bandit posterior."""

        x = np.asarray(context_features, dtype=float).reshape(-1)
        if x.shape[0] != self.n_features:
            raise ValueError(f"Expected {self.n_features} features, got {x.shape[0]}")
        with self._lock:
            rec = self._ensure_action(action)
            rec["A"] = rec["A"] + np.outer(x, x)
            rec["b"] = rec["b"] + float(reward) * x
            rec["count"] = int(rec["count"]) + 1
        _LOG.info(
            "bandit.update action=%s reward=%.4f count=%d",
            action,
            float(reward),
            self.actions[action]["count"],
        )

    def state_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "n_features": self.n_features,
                "alpha": self.alpha,
                "actions": {
                    a: {"count": int(rec["count"])} for a, rec in self.actions.items()
                },
            }


# Default action catalogue. Intent → list of admissible actions.
_DEFAULT_ACTION_REGISTRY: dict[str, list[str]] = {
    # Trading
    "analyze_trade_opportunity": ["buy", "sell", "hold", "add_to_watchlist"],
    "execute_trade": ["market_order", "limit_order", "stop_loss_order", "cancel"],
    "manage_position": ["hold", "scale_out", "add_to_position", "close_position"],
    # Business
    "inventory_decision": [
        "purchase_inventory",
        "hold_inventory",
        "sell_inventory",
        "discount_inventory",
    ],
    "pricing_decision": [
        "increase_price",
        "decrease_price",
        "dynamic_pricing",
        "hold_price",
    ],
    "marketing_decision": [
        "launch_campaign",
        "pause_campaign",
        "optimize_campaign",
        "no_action",
    ],
    # Personal
    "goal_prioritization": [
        "focus_goal_a",
        "focus_goal_b",
        "balance_goals",
        "defer_goals",
    ],
    "schedule_optimization": ["accept_meeting", "decline_meeting", "reschedule", "delegate"],
    # System
    "resource_allocation": ["scale_up", "scale_down", "maintain", "optimize"],
    "error_handling": ["retry", "fallback", "escalate", "ignore"],
    # Domain defaults (used when intent has no explicit registry entry).
    "trading_default": ["analyze", "hold", "alert"],
    "business_default": ["analyze", "monitor", "alert"],
    "personal_default": ["log", "schedule", "defer"],
    "system_default": ["monitor", "log", "alert"],
}


_TRADING_ACTIONS = frozenset(
    {
        "buy",
        "sell",
        "hold",
        "add_to_watchlist",
        "market_order",
        "limit_order",
        "stop_loss_order",
        "cancel",
        "scale_out",
        "add_to_position",
        "close_position",
        "analyze",
        "alert",
    }
)
_BUSINESS_ACTIONS = frozenset(
    {
        "purchase_inventory",
        "hold_inventory",
        "sell_inventory",
        "discount_inventory",
        "increase_price",
        "decrease_price",
        "dynamic_pricing",
        "hold_price",
        "launch_campaign",
        "pause_campaign",
        "optimize_campaign",
        "no_action",
        "monitor",
    }
)
_PERSONAL_ACTIONS = frozenset(
    {
        "focus_goal_a",
        "focus_goal_b",
        "balance_goals",
        "defer_goals",
        "accept_meeting",
        "decline_meeting",
        "reschedule",
        "delegate",
        "schedule",
        "defer",
        "log",
    }
)


class PolicyEngine:
    """Central decision policy: LinUCB bandit + Bayesian world-model context."""

    def __init__(
        self,
        n_features: int = 20,
        alpha: float = 1.0,
        *,
        action_registry: dict[str, list[str]] | None = None,
    ) -> None:
        self.n_features = int(n_features)
        self.bandit = LinUCBBandit(n_features=self.n_features, alpha=alpha)
        self.action_registry: dict[str, list[str]] = (
            dict(action_registry) if action_registry else dict(_DEFAULT_ACTION_REGISTRY)
        )

        # Lazy imports so a missing world-model module doesn't break basic use.
        try:
            from services.world_model.bayesian_world_model import BayesianWorldModel

            self._world_model_cls: type | None = BayesianWorldModel
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.debug("world_model unavailable at engine init: %s", exc)
            self._world_model_cls = None

        # Cache features keyed by (intent, domain, action) so update_from_outcome
        # uses the **exact** vector that produced the decision (world state may
        # have moved by the time the outcome arrives).
        self._recent_features: dict[tuple[str, str, str], np.ndarray] = {}
        _LOG.info(
            "PolicyEngine ready features=%d alpha=%.3f intents=%d",
            self.n_features,
            alpha,
            len(self.action_registry),
        )

    # -- decisions -------------------------------------------------------

    def decide(
        self,
        context: DecisionContext,
        available_actions: list[str] | None = None,
    ) -> DecisionOutput:
        if not isinstance(context, DecisionContext):
            raise TypeError("context must be a DecisionContext")
        actions = list(available_actions or self._get_available_actions(context))
        if not actions:
            raise ValueError(f"No available actions for intent={context.intent!r}")

        world_state = self._get_world_state(context)
        features = self._extract_features(context, world_state)
        action, expected_reward, exploration_bonus = self.bandit.select_action(
            actions, features
        )
        confidence = self._compute_confidence(expected_reward, exploration_bonus)
        reasoning = self._generate_reasoning(
            action, context, world_state, expected_reward, exploration_bonus
        )

        output = DecisionOutput(
            action=action,
            action_type=self._classify_action(action),
            confidence=confidence,
            expected_reward=expected_reward,
            reasoning=reasoning,
            context_used=asdict(context),
            world_state=world_state,
            timestamp=datetime.now(timezone.utc),
            exploration_bonus=exploration_bonus,
            features=[float(v) for v in features.tolist()],
        )

        # Cache the exact feature vector that drove the decision.
        self._recent_features[(context.intent, context.domain, action)] = features

        # Best-effort persistence (skips silently when DB / org_id missing).
        output.learning_log_id = self._log_decision(context, output)
        _LOG.info(
            "policy.decide action=%s confidence=%.3f intent=%s domain=%s",
            action,
            confidence,
            context.intent,
            context.domain,
        )
        return output

    def update_from_outcome(
        self,
        decision_context: DecisionContext,
        action: str,
        outcome: dict[str, Any],
        reward: float,
    ) -> None:
        """Update bandit weights using the cached decision-time features when
        available; otherwise re-extract from the current world state."""

        if not isinstance(decision_context, DecisionContext):
            raise TypeError("decision_context must be a DecisionContext")
        try:
            r = float(reward)
        except Exception as exc:
            raise ValueError(f"reward must be numeric, got {reward!r}") from exc

        cache_key = (decision_context.intent, decision_context.domain, action)
        features = self._recent_features.get(cache_key)
        if features is None:
            world_state = self._get_world_state(decision_context)
            features = self._extract_features(decision_context, world_state)
        self.bandit.update(action, features, r)
        self._log_outcome(decision_context, action, outcome, r)

    # -- features --------------------------------------------------------

    def _extract_features(
        self,
        context: DecisionContext,
        world_state: dict[str, Any],
    ) -> np.ndarray:
        now = datetime.now(timezone.utc)

        # Context features (10)
        ctx_feats: list[float] = [
            1.0,  # bias
            _bucket_index(context.domain, _DOMAIN_BUCKETS),
            float(max(0.0, min(1.0, float(context.risk_tolerance or 0.0)))),
            _bucket_index(context.time_horizon, _TIME_HORIZON_BUCKETS),
            min(len(context.constraints) / 10.0, 1.0),
            now.hour / 24.0,
            now.weekday() / 6.0,
            min(float(context.user_id or 0) / 1000.0, 1.0),
            min(len(context.metadata) / 10.0, 1.0),
            _stable_unit_hash(context.intent),
        ]

        # World-model features (10)
        wf = (world_state or {}).get("features") or {}
        world_feats: list[float] = [
            float(wf.get("market_regime_confidence", 0.5)),
            float(wf.get("business_health_score", 0.5)),
            float(wf.get("recent_success_rate", 0.5)),
            float(wf.get("volatility_score", 0.5)),
            float(wf.get("trend_strength", 0.5)),
            float(wf.get("decision_fatigue", 0.0)),
            float(wf.get("capital_utilization", 0.5)),
            float(wf.get("risk_exposure", 0.0)),
            float(wf.get("opportunity_score", 0.5)),
            float(wf.get("system_load", 0.3)),
        ]

        all_feats = ctx_feats + world_feats
        if len(all_feats) < self.n_features:
            all_feats.extend([0.0] * (self.n_features - len(all_feats)))
        else:
            all_feats = all_feats[: self.n_features]
        arr = np.asarray(all_feats, dtype=float)
        # Defence in depth: scrub NaN / inf so the bandit math stays stable.
        return np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=-1.0)

    def _get_world_state(self, context: DecisionContext) -> dict[str, Any]:
        if self._world_model_cls is None:
            return {"prediction": None, "features": {}}
        try:
            engine = self._world_model_cls(
                organization_id=context.organization_id,
                user_id=context.user_id,
            )
            predictions: dict[str, dict[str, Any]] = {}
            for outcome in _WORLD_OUTCOMES:
                try:
                    predictions[outcome] = engine.predict_outcome(outcome)
                except Exception:
                    continue
            features = self._world_features_from_predictions(context, predictions)
            return {"prediction": predictions, "features": features}
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.debug("world_model.query_failed: %s", exc)
            return {"prediction": None, "features": {}}

    @staticmethod
    def _world_features_from_predictions(
        context: DecisionContext, predictions: dict[str, dict[str, Any]]
    ) -> dict[str, float]:
        if not predictions:
            return {}
        avg_evidence = np.mean(
            [float(p.get("evidence_n") or 0) for p in predictions.values()]
        )
        regime_conf = min(1.0, avg_evidence / 30.0)
        risk_p = float((predictions.get("trading_drawdown_alert") or {}).get("p", 0.0))
        cash_p = float((predictions.get("cash_crunch_30d") or {}).get("p", 0.0))
        stockout_p = float((predictions.get("inventory_stockout_7d") or {}).get("p", 0.0))
        decision_quality_drop = float(
            (predictions.get("system_decision_quality_drop") or {}).get("p", 0.0)
        )
        rev_up = float((predictions.get("revenue_up_next_week") or {}).get("p", 0.5))

        # Domain-aware mapping into the 10 named slots used by ``_extract_features``.
        return {
            "market_regime_confidence": float(regime_conf),
            "business_health_score": float(max(0.0, 1.0 - cash_p)),
            "recent_success_rate": float(max(0.0, 1.0 - decision_quality_drop)),
            "volatility_score": float(risk_p),
            "trend_strength": float(rev_up),
            "decision_fatigue": float(min(1.0, decision_quality_drop)),
            "capital_utilization": float(min(1.0, cash_p + 0.4)),
            "risk_exposure": float(risk_p),
            "opportunity_score": float(rev_up),
            "system_load": 0.3 + 0.5 * float(decision_quality_drop),
        }

    # -- registry / typing ----------------------------------------------

    def _get_available_actions(self, context: DecisionContext) -> list[str]:
        actions = self.action_registry.get(context.intent)
        if actions:
            return list(actions)
        domain_default = f"{(context.domain or 'system').strip().lower()}_default"
        return list(self.action_registry.get(domain_default, []))

    def _classify_action(self, action: str) -> str:
        a = (action or "").strip().lower()
        if a in _TRADING_ACTIONS:
            return "trading"
        if a in _BUSINESS_ACTIONS:
            return "business"
        if a in _PERSONAL_ACTIONS:
            return "personal"
        return "system"

    # -- scoring ---------------------------------------------------------

    @staticmethod
    def _compute_confidence(expected_reward: float, exploration_bonus: float) -> float:
        # exploration_bonus near 0 → high confidence; cap at 2.0 for stability.
        uncertainty = min(max(float(exploration_bonus), 0.0), 2.0) / 2.0
        certainty = 1.0 - uncertainty
        # Squashing of expected reward into a [0, 1] modifier (centered on 0).
        reward_mod = 1.0 / (1.0 + np.exp(-float(expected_reward)))
        score = float(certainty) * float(reward_mod)
        return max(0.0, min(1.0, score))

    @staticmethod
    def _generate_reasoning(
        action: str,
        context: DecisionContext,
        world_state: dict[str, Any],
        expected_reward: float,
        exploration_bonus: float,
    ) -> list[str]:
        reasoning: list[str] = [f"Selected action '{action}' via LinUCB contextual bandit."]
        if expected_reward > 0.5:
            reasoning.append(
                f"High expected reward ({expected_reward:.2f}) for this action."
            )
        elif expected_reward < -0.5:
            reasoning.append(
                f"Low expected reward ({expected_reward:.2f}); exploring alternatives."
            )
        else:
            reasoning.append(f"Moderate expected reward ({expected_reward:.2f}).")
        if exploration_bonus > 0.5:
            reasoning.append("High uncertainty — exploring to gather more evidence.")
        else:
            reasoning.append("Low uncertainty — exploiting known good action.")
        reasoning.append(f"Risk tolerance: {context.risk_tolerance:.2f}")
        reasoning.append(f"Time horizon: {context.time_horizon}")

        predictions = (world_state or {}).get("prediction") or {}
        if isinstance(predictions, dict):
            risk = predictions.get("trading_drawdown_alert") or {}
            if isinstance(risk, dict) and risk.get("evidence_n"):
                reasoning.append(
                    f"World model: trading_drawdown_alert p={float(risk.get('p', 0)):.2f}"
                    f" (evidence_n={int(risk.get('evidence_n', 0))})"
                )
        return reasoning

    # -- persistence -----------------------------------------------------

    def _log_decision(
        self, context: DecisionContext, output: DecisionOutput
    ) -> int | None:
        """Best-effort write into ``learning_logs``. Returns the row id or None.

        ``LearningLog.organization_id`` is NOT NULL, so we silently skip the
        write when the caller did not pass an ``organization_id``.
        """

        if context.organization_id is None:
            return None
        factory = get_session_factory()
        if factory is None:
            return None
        try:
            with factory() as session:
                row = LearningLog(
                    organization_id=int(context.organization_id),
                    user_id=int(context.user_id) if context.user_id is not None else None,
                    source_type="policy_engine",
                    action_type=str(output.action_type or "")[:128],
                    outcome="decision_pending",
                    lesson_summary=" | ".join(output.reasoning)[:4000],
                    context={
                        "intent": context.intent,
                        "domain": context.domain,
                        "risk_tolerance": context.risk_tolerance,
                        "time_horizon": context.time_horizon,
                        "constraints": context.constraints,
                        "metadata": context.metadata,
                    },
                    input_data_json={
                        "features": output.features,
                        "world_state": _safe_json_dict(output.world_state),
                    },
                    outcome_json={
                        "action": output.action,
                        "expected_reward": output.expected_reward,
                        "exploration_bonus": output.exploration_bonus,
                        "confidence": output.confidence,
                    },
                    result={"phase": "decided"},
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return int(row.id)
        except Exception as exc:
            _LOG.warning("policy_engine._log_decision failed: %s", exc)
            return None

    def _log_outcome(
        self,
        context: DecisionContext,
        action: str,
        outcome: dict[str, Any],
        reward: float,
    ) -> None:
        if context.organization_id is None:
            return
        factory = get_session_factory()
        if factory is None:
            return
        try:
            with factory() as session:
                # Find the most recent pending decision for this user/action.
                stmt = (
                    select(LearningLog)
                    .where(LearningLog.organization_id == int(context.organization_id))
                    .where(LearningLog.source_type == "policy_engine")
                    .where(LearningLog.action_type.is_not(None))
                    .order_by(LearningLog.created_at.desc())
                    .limit(40)
                )
                candidate: LearningLog | None = None
                for r in session.execute(stmt).scalars().all():
                    payload = r.outcome_json or {}
                    if (
                        isinstance(payload, dict)
                        and payload.get("action") == action
                        and (r.outcome or "") == "decision_pending"
                    ):
                        candidate = r
                        break
                if candidate is None:
                    return
                outcome_json = dict(candidate.outcome_json or {})
                outcome_json.update(
                    {
                        "actual": _safe_json_dict(outcome),
                        "reward": float(reward),
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                candidate.outcome_json = outcome_json
                candidate.outcome = "outcome_recorded"
                candidate.success = bool(reward > 0)
                candidate.result = {"phase": "resolved", "reward": float(reward)}
                session.commit()
        except Exception as exc:
            _LOG.warning("policy_engine._log_outcome failed: %s", exc)


def _safe_json_dict(value: Any) -> Any:
    """Coerce arbitrary payloads to JSON-safe primitives for JSONB columns."""

    try:
        json.dumps(value, default=str)
        return value
    except Exception:
        return {"_repr": str(value)[:2000]}


# ---------------------------------------------------------------------------
# Singleton accessor (process-wide)
# ---------------------------------------------------------------------------


_policy_engine: PolicyEngine | None = None
_policy_engine_lock = threading.Lock()


def get_policy_engine() -> PolicyEngine:
    """Return a process-wide singleton ``PolicyEngine``."""

    global _policy_engine
    if _policy_engine is None:
        with _policy_engine_lock:
            if _policy_engine is None:
                _policy_engine = PolicyEngine(n_features=20, alpha=1.0)
    return _policy_engine


def reset_policy_engine() -> None:
    """Reset the singleton (test-only helper; not for production hot paths)."""

    global _policy_engine
    with _policy_engine_lock:
        _policy_engine = None


__all__ = [
    "AutonomyPolicy",
    "DEFAULT_POLICY",
    "DecisionContext",
    "DecisionOutput",
    "LinUCBBandit",
    "PolicyEngine",
    "get_policy_engine",
    "load_autonomy_policy",
    "policy_allows_auto_approve",
    "reset_policy_engine",
]
