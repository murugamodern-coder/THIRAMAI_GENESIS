"""Counterfactual analysis: "what would have happened if I had done X instead?"

For a recorded decision (a :class:`core.db.models.LearningLog` row) this
engine simulates a set of plausible alternative actions, scores each against
the world model and historical outcomes, and reports the *regret*:

    regret = best_alternative.expected_reward - actual_reward

A non-positive regret means the realised decision matched or beat every
simulated alternative.

Spec deviations (deliberate fixes for issues in the original prompt)
--------------------------------------------------------------------

* ``LearningLog`` has **no** ``domain`` column - the spec read ``log.domain``
  in three places. Domain is now extracted from ``log.context["domain"]``
  with sensible defaults.
* ``BayesianWorldModel.predict_outcome`` returns ``{"p", "evidence_n", ...}``,
  not ``{"probability", "confidence"}``. Confidence is derived from
  ``evidence_n`` using the same weighting the world model uses internally.
* ``LearningLog.outcome != None`` is a no-op (the column is non-nullable);
  the historical lookup now filters on ``success.is_not(None)``.
* The spec called ``np.random.normal`` which clobbers the global numpy RNG.
  We use a per-call :class:`numpy.random.Generator` seeded from a stable
  hash of ``(decision_id, action)`` so repeated runs of the same scenario
  give the same noise, but other components are unaffected.
* ``get_session_factory()`` can legitimately return ``None`` when no DB is
  configured. Both engine and simulator now treat that case gracefully.
* ``BayesianWorldModel`` is injectable so tests don't need a real DB.
"""

from __future__ import annotations

import json
import logging
import threading
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

import numpy as np

from services.world_model.bayesian_world_model import BayesianWorldModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_session_factory() -> Callable[[], Any] | None:
    """Return a callable session factory or ``None`` when no DB is configured.

    Wrapped in try/except because importing :mod:`core.database` can itself
    fail in some lightweight test contexts (e.g. when the engine URL is
    invalid)."""
    try:
        from core.database import get_session_factory

        factory = get_session_factory()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("counterfactual: session factory import failed: %s", exc)
        return None
    return factory


def _stable_seed(*parts: Any) -> int:
    """Deterministic 32-bit seed from arbitrary inputs.

    We use ``zlib.adler32`` instead of ``hash()`` because Python salts hashes
    per-process by default - the spec used ``np.random.seed(hash(...))``
    which silently produced different noise across deployments."""
    payload = "::".join("" if p is None else str(p) for p in parts)
    return zlib.adler32(payload.encode("utf-8")) & 0xFFFFFFFF


def _domain_from_context(ctx: dict[str, Any] | None, default: str = "business") -> str:
    if not ctx:
        return default
    domain = ctx.get("domain")
    if isinstance(domain, str) and domain.strip():
        return domain.strip().lower()
    return default


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CounterfactualScenario:
    """One simulated alternative action with its predicted outcome."""

    action: str
    simulated_outcome: dict[str, Any]
    expected_reward: float
    confidence: float
    reasoning: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "simulated_outcome": dict(self.simulated_outcome),
            "expected_reward": float(self.expected_reward),
            "confidence": float(self.confidence),
            "reasoning": self.reasoning,
        }


@dataclass
class CounterfactualAnalysis:
    """The full analysis of a single past decision."""

    decision_id: int
    actual_action: str
    actual_outcome: dict[str, Any]
    actual_reward: float
    alternatives: list[CounterfactualScenario] = field(default_factory=list)
    best_alternative: CounterfactualScenario | None = None
    regret: float = 0.0
    lesson: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "actual_action": self.actual_action,
            "actual_outcome": dict(self.actual_outcome),
            "actual_reward": float(self.actual_reward),
            "alternatives": [s.as_dict() for s in self.alternatives],
            "best_alternative": self.best_alternative.as_dict() if self.best_alternative else None,
            "regret": float(self.regret),
            "lesson": self.lesson,
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Outcome simulator
# ---------------------------------------------------------------------------


_DOMAIN_OUTCOME_MAP: dict[str, str] = {
    "trading": "trading_win_streak",
    "business": "growth_unlocked",
    "personal": "founder_burnout_risk",
    "system": "growth_unlocked",
}


class OutcomeSimulator:
    """Predict the reward of a hypothetical action via world model + history.

    The blended score is::

        if any historical reward exists:
            70% historical mean + 30% world-model prediction
        else:
            world-model prediction only
        + small noise scaled by (1 - world_model_confidence)
    """

    def __init__(
        self,
        *,
        world_model: BayesianWorldModel | None = None,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._world_model = world_model
        # ``None`` means "no DB available" - simulate purely from world model.
        self._session_factory = session_factory if session_factory is not None else _safe_session_factory()

    @property
    def world_model(self) -> BayesianWorldModel:
        if self._world_model is None:
            self._world_model = BayesianWorldModel()
        return self._world_model

    # -- public --------------------------------------------------------

    def simulate(
        self,
        context: dict[str, Any],
        action: str,
        domain: str = "business",
        *,
        decision_id: int | None = None,
    ) -> tuple[dict[str, Any], float]:
        """Simulate the outcome of running ``action`` in ``context``.

        Returns ``(outcome_dict, blended_reward)``."""
        prediction = self._predict_outcome(context, action, domain)
        historical = self._historical_lookup(context, action, domain)

        wm_reward = float(prediction["reward"])
        if historical is not None:
            blended = 0.7 * float(historical) + 0.3 * wm_reward
        else:
            blended = wm_reward

        confidence = float(prediction["confidence"])
        # Stable per-(scenario) RNG so repeated runs of the same counterfactual
        # produce the same noise. Per-call ``Generator`` so we never touch
        # ``np.random`` global state.
        rng = np.random.default_rng(_stable_seed(decision_id, action, domain))
        noise = float(rng.normal(0.0, 0.1 * (1.0 - confidence)))
        blended += noise

        outcome = {
            "success": bool(blended > 0),
            "reward": blended,
            "confidence": confidence,
            "source": "simulation",
            "world_model_prediction": prediction,
            "historical_match": historical is not None,
            "historical_reward": float(historical) if historical is not None else None,
            "noise": noise,
        }
        return outcome, blended

    # -- internals -----------------------------------------------------

    def _predict_outcome(
        self, context: dict[str, Any], action: str, domain: str
    ) -> dict[str, Any]:
        outcome_name = _DOMAIN_OUTCOME_MAP.get(domain, "growth_unlocked")
        try:
            conditions = {"action": action, "domain": domain}
            for key, value in (context or {}).items():
                if isinstance(value, (int, float, str, bool)):
                    conditions[key] = value
            raw = self.world_model.predict_outcome(outcome_name, conditions=conditions)
        except Exception as exc:
            logger.warning("counterfactual: world model prediction failed: %s", exc)
            return {"reward": 0.0, "confidence": 0.3, "probability": 0.5, "outcome": outcome_name}

        prob = float(raw.get("p", 0.5))
        evidence_n = int(raw.get("evidence_n", 0) or 0)
        # Match the world model's own internal evidence weighting (n/30 capped).
        confidence = max(0.1, min(1.0, evidence_n / 30.0))
        reward = 2.0 * prob - 1.0  # map [0,1] -> [-1,1]
        return {
            "reward": reward,
            "confidence": confidence,
            "probability": prob,
            "outcome": outcome_name,
            "evidence_n": evidence_n,
        }

    def _historical_lookup(
        self, context: dict[str, Any], action: str, domain: str
    ) -> float | None:
        factory = self._session_factory
        if factory is None:
            return None
        try:
            session = factory()
        except Exception as exc:
            logger.debug("counterfactual: session open failed: %s", exc)
            return None
        try:
            from core.db.models import LearningLog

            rows = (
                session.query(LearningLog)
                .filter(LearningLog.action_type == action)
                .filter(LearningLog.success.is_not(None))
                .order_by(LearningLog.created_at.desc())
                .limit(20)
                .all()
            )
            if not rows:
                return None
            rewards: list[float] = []
            for row in rows:
                # Schema has no `domain` column - read from the stored context.
                row_domain = _domain_from_context(getattr(row, "context", None), default=domain)
                if row_domain != domain:
                    continue
                payload = getattr(row, "outcome_json", None) or {}
                if isinstance(payload, dict):
                    reward = payload.get("reward")
                    if reward is not None:
                        try:
                            rewards.append(float(reward))
                        except (TypeError, ValueError):
                            continue
                if not rewards and getattr(row, "success", None) is not None:
                    rewards.append(1.0 if row.success else -0.5)
            if not rewards:
                return None
            # Cap at 10 most recent to bound the lookup.
            return float(np.mean(rewards[:10]))
        except Exception as exc:
            logger.warning("counterfactual: historical lookup failed: %s", exc)
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Counterfactual engine
# ---------------------------------------------------------------------------


_DOMAIN_ALTERNATIVES: dict[str, tuple[str, ...]] = {
    "trading": ("buy", "sell", "hold", "hedge"),
    "business": ("invest", "save", "expand", "optimize"),
    "personal": ("focus", "delegate", "defer", "decline"),
    "system": ("scale_up", "scale_down", "maintain", "optimize"),
}


class CounterfactualEngine:
    """Top-level entry point for counterfactual analysis."""

    def __init__(
        self,
        *,
        simulator: OutcomeSimulator | None = None,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._simulator = simulator
        self._session_factory = session_factory if session_factory is not None else _safe_session_factory()
        self._lock = threading.Lock()

    @property
    def simulator(self) -> OutcomeSimulator:
        if self._simulator is None:
            self._simulator = OutcomeSimulator(session_factory=self._session_factory)
        return self._simulator

    # -- public --------------------------------------------------------

    def analyze(
        self,
        decision_id: int,
        alternative_actions: Iterable[str] | None = None,
    ) -> CounterfactualAnalysis:
        """Analyse a recorded decision against alternative actions."""
        log = self._load_decision(decision_id)
        if log is None:
            raise ValueError(f"decision {decision_id} not found")

        context = self._extract_context(log)
        domain = _domain_from_context(context)
        actual_action = str(getattr(log, "action_type", "") or "")
        actual_reward = self._extract_reward(log)
        actual_outcome = dict(getattr(log, "outcome_json", None) or {})

        if alternative_actions is None:
            alts: list[str] = list(self._infer_alternatives(domain))
        else:
            alts = [a for a in alternative_actions if isinstance(a, str) and a]

        # Drop the action we actually took.
        alts = [a for a in alts if a != actual_action]

        scenarios: list[CounterfactualScenario] = []
        for alt in alts:
            outcome, reward = self.simulator.simulate(
                context, alt, domain=domain, decision_id=decision_id
            )
            scenarios.append(
                CounterfactualScenario(
                    action=alt,
                    simulated_outcome=outcome,
                    expected_reward=reward,
                    confidence=float(outcome.get("confidence", 0.5)),
                    reasoning=self._generate_reasoning(alt, outcome),
                )
            )

        best = max(scenarios, key=lambda s: s.expected_reward) if scenarios else None
        regret = (best.expected_reward - actual_reward) if best is not None else 0.0
        lesson = self._generate_lesson(actual_action, actual_reward, best, regret)

        analysis = CounterfactualAnalysis(
            decision_id=decision_id,
            actual_action=actual_action,
            actual_outcome=actual_outcome,
            actual_reward=actual_reward,
            alternatives=scenarios,
            best_alternative=best,
            regret=regret,
            lesson=lesson,
        )
        logger.info(
            "counterfactual: decision_id=%d actual=%s alternatives=%d regret=%.3f",
            decision_id, actual_action, len(scenarios), regret,
        )
        return analysis

    # -- internals -----------------------------------------------------

    def _load_decision(self, decision_id: int) -> Any | None:
        factory = self._session_factory
        if factory is None:
            return None
        try:
            from core.db.models import LearningLog
            from sqlalchemy import select

            with factory() as session:
                stmt = select(LearningLog).where(LearningLog.id == decision_id)
                return session.execute(stmt).scalar_one_or_none()
        except Exception as exc:
            logger.warning("counterfactual: load_decision failed: %s", exc)
            return None

    @staticmethod
    def _extract_context(log: Any) -> dict[str, Any]:
        raw = getattr(log, "context", None)
        if isinstance(raw, dict):
            return dict(raw)
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except (ValueError, TypeError):
                pass
        return {
            "domain": "business",
            "user_id": getattr(log, "user_id", None),
            "organization_id": getattr(log, "organization_id", None),
        }

    @staticmethod
    def _infer_alternatives(domain: str) -> tuple[str, ...]:
        return _DOMAIN_ALTERNATIVES.get(
            domain, ("action_a", "action_b", "no_action")
        )

    @staticmethod
    def _extract_reward(log: Any) -> float:
        payload = getattr(log, "outcome_json", None)
        if isinstance(payload, dict):
            value = payload.get("reward")
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
        success = getattr(log, "success", None)
        if success is True:
            return 1.0
        if success is False:
            return -0.5
        return 0.0

    @staticmethod
    def _generate_reasoning(action: str, outcome: dict[str, Any]) -> str:
        confidence = float(outcome.get("confidence", 0.5))
        reward = float(outcome.get("reward", 0.0))
        if reward > 0.5:
            tone = "would likely succeed"
        elif reward > 0:
            tone = "might succeed"
        elif reward > -0.5:
            tone = "might fail"
        else:
            tone = "would likely fail"
        return f"action '{action}' {tone} (reward={reward:.2f}, confidence={confidence:.2f})"

    @staticmethod
    def _generate_lesson(
        actual_action: str,
        actual_reward: float,
        best_alt: CounterfactualScenario | None,
        regret: float,
    ) -> str:
        if best_alt is None:
            return f"no comparable alternative for '{actual_action}'"
        if regret <= 0:
            return f"good decision - '{actual_action}' beat every simulated alternative"
        if regret < 0.1:
            return f"good decision - '{actual_action}' was near-optimal"
        if regret > 0.5:
            return (
                f"significant regret - '{best_alt.action}' would have been "
                f"{regret:.2f} better than '{actual_action}'"
            )
        return (
            f"minor regret - '{best_alt.action}' would have been slightly "
            f"better than '{actual_action}'"
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_singleton: CounterfactualEngine | None = None
_singleton_lock = threading.Lock()


def get_counterfactual_engine() -> CounterfactualEngine:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = CounterfactualEngine()
    return _singleton


def reset_counterfactual_engine() -> None:
    """Test-only helper; drops the singleton so the next access rebuilds it."""
    global _singleton
    with _singleton_lock:
        _singleton = None


__all__ = [
    "CounterfactualAnalysis",
    "CounterfactualEngine",
    "CounterfactualScenario",
    "OutcomeSimulator",
    "get_counterfactual_engine",
    "reset_counterfactual_engine",
]
