"""
DecisionBrain V2 — A/B-routed migration shim that gradually moves traffic from
the legacy Groq-only ``services.decision_brain.run_decision_engine_sync`` to
the new central :class:`services.policy_engine.PolicyEngine`.

Key facts about *this* codebase that the original prompt got wrong and that
this implementation corrects:

* The legacy brain is a **function** (``run_decision_engine_sync``), not a
  class with an async ``decide()`` method.
* ``core.logger`` does not exist — we use :mod:`logging`.
* ``LearningLog`` has no ``timestamp`` / ``confidence`` columns — confidence
  and reward live inside ``outcome_json``; the timestamp column is
  ``created_at``.

A/B routing is deterministic per ``user_id`` (same user → same variant) so
metric comparison stays meaningful. Outcome rewards are routed back to whichever
brain produced the decision (we never feed legacy-brain rewards into the
policy engine bandit).

Environment variables
---------------------
``THIRAMAI_DECISION_AB_TEST`` / ``DECISION_AB_TEST`` — ``true`` (default) to
enable A/B routing; ``false`` forces 100% PolicyEngine.

``THIRAMAI_POLICY_ENGINE_PCT`` / ``POLICY_ENGINE_PCT`` / ``POLICY_ENGINE_PERCENTAGE`` —
percentage of traffic routed to PolicyEngine when A/B is enabled. Default ``50``.

``THIRAMAI_DISABLE_LEGACY_FALLBACK`` / ``DISABLE_LEGACY_FALLBACK`` — when true,
``PolicyEngine.decide`` failures re-raise instead of calling the Groq legacy path.

``THIRAMAI_POLICY_SAFE_FALLBACK`` — when true (default), PolicyEngine / circuit failures
emit an in-process ``safe_fallback`` V2 payload (``no_action``) before Groq legacy.
When false, failures go straight to legacy (if fallback allowed).

Circuit breaker env: ``THIRAMAI_POLICY_CB_FAILURE_THRESHOLD``,
``THIRAMAI_POLICY_CB_SUCCESS_THRESHOLD``, ``THIRAMAI_POLICY_CB_TIMEOUT_SECONDS``
(aliases ``CIRCUIT_BREAKER_*`` also read).
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import threading
from datetime import datetime, timezone
from typing import Any

from core.database import get_session_factory
from core.db.models import LearningLog
from services.decision_brain import run_decision_engine_sync
from services.policy_engine import DecisionContext, PolicyEngine, get_policy_engine
from services.policy_engine_wrapper import (
    build_safe_fallback_v2_payload,
    circuit_runtime_rejected,
    guarded_policy_decide,
)

_LOG = logging.getLogger(__name__)


_PRIORITY_TO_CONFIDENCE = {"high": 0.8, "medium": 0.55, "low": 0.3}


def _record_ai_quality_from_v2(v2: dict[str, Any]) -> None:
    if not _bool_env("THIRAMAI_AI_QUALITY_TRACKING", default=True):
        return
    try:
        from services.ai_quality_tracker import get_quality_tracker

        get_quality_tracker().record_decision(
            action=str(v2.get("action") or ""),
            confidence=float(v2.get("confidence") or 0.0),
            source=str(v2.get("source") or "unknown"),
            metadata={
                "user_id": v2.get("user_id"),
                "organization_id": v2.get("organization_id"),
                "intent": v2.get("intent"),
            },
        )
    except Exception:
        pass


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


class DecisionBrainV2:
    """A/B-routed wrapper over PolicyEngine + legacy decision brain."""

    def __init__(self, *, policy_engine: PolicyEngine | None = None) -> None:
        self.policy_engine: PolicyEngine = policy_engine or get_policy_engine()
        self.ab_test_enabled = _bool_env(
            "THIRAMAI_DECISION_AB_TEST", "DECISION_AB_TEST", default=True
        )
        pct = _float_env(
            "THIRAMAI_POLICY_ENGINE_PCT",
            "POLICY_ENGINE_PCT",
            "POLICY_ENGINE_PERCENTAGE",
            default=50.0,
        )
        self.policy_engine_percentage = max(0.0, min(100.0, pct))
        _LOG.info(
            "DecisionBrainV2 ready ab_test=%s policy_pct=%.1f",
            self.ab_test_enabled,
            self.policy_engine_percentage,
        )

    # -- routing --------------------------------------------------------

    def _should_use_policy_engine(self, user_id: int | None) -> bool:
        if not self.ab_test_enabled:
            return True
        if user_id is not None:
            return (int(user_id) % 100) < self.policy_engine_percentage
        return random.random() * 100.0 < self.policy_engine_percentage

    # -- public API -----------------------------------------------------

    async def decide(
        self,
        intent: str,
        context: dict[str, Any],
        user_id: int | None = None,
        domain: str = "business",
        organization_id: int | None = None,
    ) -> dict[str, Any]:
        """Route to PolicyEngine or legacy brain and return a unified payload.

        The unified payload always contains: ``action``, ``action_type``,
        ``confidence``, ``reasoning``, ``expected_reward``, ``source``,
        ``timestamp``, plus pass-through fields ``intent``, ``domain``,
        ``user_id``, ``organization_id`` so :meth:`record_outcome` does not
        need extra context from the caller.
        """

        ctx = dict(context or {})
        if self._should_use_policy_engine(user_id):
            return await self._decide_with_policy_engine(
                intent, ctx, user_id, domain, organization_id
            )
        return await self._decide_with_legacy(
            intent, ctx, user_id, domain, organization_id
        )

    async def record_outcome(
        self,
        decision: dict[str, Any],
        outcome: dict[str, Any],
        reward: float,
    ) -> None:
        """Send the observed outcome to whichever brain produced ``decision``.

        Legacy decisions still get logged for A/B accounting; only PolicyEngine
        decisions update the bandit weights.
        """

        if not isinstance(decision, dict):
            raise TypeError("decision must be a dict")
        source = str(decision.get("source") or "")
        action = str(decision.get("action") or "")
        if not action:
            return

        if source == "policy_engine":
            decision_context = DecisionContext(
                intent=str(decision.get("intent") or "unknown"),
                domain=str(decision.get("domain") or "system"),
                user_id=decision.get("user_id"),
                organization_id=decision.get("organization_id"),
                risk_tolerance=float(decision.get("risk_tolerance") or 0.5),
                time_horizon=str(decision.get("time_horizon") or "short"),
                constraints=dict(decision.get("constraints") or {}),
                metadata=dict(decision.get("metadata") or {}),
            )
            try:
                await asyncio.to_thread(
                    self.policy_engine.update_from_outcome,
                    decision_context,
                    action,
                    outcome,
                    float(reward),
                )
            except Exception as exc:
                _LOG.warning("policy_engine.update_from_outcome failed: %s", exc)
            return

        if source == "legacy_brain":
            await asyncio.to_thread(
                _legacy_record_outcome,
                decision.get("learning_log_id"),
                outcome,
                float(reward),
            )
            return

        if source == "safe_fallback":
            _LOG.debug("record_outcome: skip bandit update for safe_fallback")
            return

        _LOG.debug("record_outcome: ignoring decision with source=%r", source)

    # -- variants -------------------------------------------------------

    async def _decide_with_policy_engine(
        self,
        intent: str,
        context: dict[str, Any],
        user_id: int | None,
        domain: str,
        organization_id: int | None,
    ) -> dict[str, Any]:
        decision_context = DecisionContext(
                intent=intent,
                domain=domain,
                user_id=user_id,
                organization_id=organization_id,
                risk_tolerance=float(context.get("risk_tolerance", 0.5)),
                time_horizon=str(context.get("time_horizon", "short")),
                constraints=dict(context.get("constraints") or {}),
                metadata=dict(context),
            )
        strict = _bool_env(
            "THIRAMAI_DISABLE_LEGACY_FALLBACK",
            "DISABLE_LEGACY_FALLBACK",
            default=False,
        )
        safe_fb = _bool_env("THIRAMAI_POLICY_SAFE_FALLBACK", default=True)

        try:
            output = await asyncio.to_thread(guarded_policy_decide, self.policy_engine, decision_context)
        except Exception as exc:
            try:
                from services.observability.decision_metrics import track_policy_engine_failure

                track_policy_engine_failure()
            except Exception:
                pass
            _LOG.error(
                "PolicyEngine.decide failed user_id=%s org_id=%s: %s",
                user_id,
                organization_id,
                exc,
                exc_info=True,
            )
            if strict:
                raise
            if safe_fb:
                try:
                    from services.observability.decision_metrics import (
                        track_decision_confidence,
                        track_decision_route,
                        track_safe_fallback,
                    )

                    track_safe_fallback()
                    track_decision_route("safe_fallback")
                    track_decision_confidence(0.3, engine="safe_fallback")
                except Exception:
                    pass
                _LOG.warning(
                    "PolicyEngine unavailable — safe_fallback (reason=%s circuit=%s)",
                    exc,
                    circuit_runtime_rejected(exc),
                )
                fb = build_safe_fallback_v2_payload(
                    reason=str(exc),
                    intent=intent,
                    domain=domain,
                    user_id=user_id,
                    organization_id=organization_id,
                    decision_context=decision_context,
                    policy_engine=self.policy_engine,
                )
                _record_ai_quality_from_v2(fb)
                return fb
            _LOG.warning("PolicyEngine.decide failed — falling back to legacy: %s", exc)
            return await self._decide_with_legacy(
                intent, context, user_id, domain, organization_id
            )

        try:
            from services.observability.decision_metrics import (
                track_decision_confidence,
                track_decision_route,
                track_policy_engine_wrapped_success,
            )

            track_policy_engine_wrapped_success()
            track_decision_route("policy_engine")
            track_decision_confidence(float(output.confidence), engine="policy_engine")
        except Exception:
            pass

        out = {
            "action": output.action,
            "action_type": output.action_type,
            "confidence": output.confidence,
            "reasoning": list(output.reasoning),
            "expected_reward": output.expected_reward,
            "exploration_bonus": output.exploration_bonus,
            "source": "policy_engine",
            "timestamp": output.timestamp.isoformat(),
            "learning_log_id": output.learning_log_id,
            # Pass-through context for record_outcome:
            "intent": intent,
            "domain": domain,
            "user_id": user_id,
            "organization_id": organization_id,
            "risk_tolerance": decision_context.risk_tolerance,
            "time_horizon": decision_context.time_horizon,
            "constraints": decision_context.constraints,
            "metadata": decision_context.metadata,
        }
        _record_ai_quality_from_v2(out)
        return out

    async def _decide_with_legacy(
        self,
        intent: str,
        context: dict[str, Any],
        user_id: int | None,
        domain: str,
        organization_id: int | None,
    ) -> dict[str, Any]:
        user_message = str(context.get("user_message") or context.get("message") or intent)
        oid_for_legacy = int(organization_id or context.get("organization_id") or 0)
        try:
            raw = await asyncio.to_thread(
                run_decision_engine_sync,
                user_message,
                oid_for_legacy,
                actor_role_name=str(context.get("actor_role_name") or "") or None,
                user_id=user_id,
                correlation_id=context.get("correlation_id"),
            )
        except Exception as exc:
            _LOG.error("legacy decision_brain raised: %s", exc)
            raw = {"ok": False, "error": str(exc), "decision": None}

        decision_payload = raw.get("decision") if isinstance(raw, dict) else None
        if isinstance(decision_payload, dict):
            action = str(decision_payload.get("action") or "noop")
            priority = str(decision_payload.get("priority") or "low").lower()
            confidence = float(_PRIORITY_TO_CONFIDENCE.get(priority, 0.4))
            rationale = str(decision_payload.get("rationale") or "")
            reasoning = [rationale] if rationale else ["Legacy brain decision."]
            expected_reward = 0.0
        else:
            err = str((raw or {}).get("error") or "legacy_no_decision")
            action = "noop"
            confidence = 0.0
            reasoning = [f"Legacy brain unavailable: {err}"]
            expected_reward = 0.0

        action_type = self.policy_engine._classify_action(action)
        timestamp = datetime.now(timezone.utc)

        # Mirror policy-engine logging so A/B metrics can compare like-for-like.
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

        try:
            from services.observability.decision_metrics import (
                track_decision_confidence,
                track_decision_route,
            )

            track_decision_route("legacy")
            track_decision_confidence(float(confidence), engine="legacy")
        except Exception:
            pass

        out = {
            "action": action,
            "action_type": action_type,
            "confidence": confidence,
            "reasoning": reasoning,
            "expected_reward": expected_reward,
            "exploration_bonus": 0.0,
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
            "legacy_raw": {
                "ok": bool((raw or {}).get("ok")),
                "validation_error": (raw or {}).get("validation_error"),
                "safety_error": (raw or {}).get("safety_error"),
            },
        }
        _record_ai_quality_from_v2(out)
        return out


# ---------------------------------------------------------------------------
# Legacy persistence helpers (kept module-level for thread safety)
# ---------------------------------------------------------------------------


def _legacy_log_decision(
    *,
    organization_id: int | None,
    user_id: int | None,
    intent: str,
    domain: str,
    action: str,
    action_type: str,
    confidence: float,
    reasoning: list[str],
    decision_payload: dict[str, Any] | None,
    raw: dict[str, Any],
    timestamp: datetime,
) -> int | None:
    """Persist a ``LearningLog`` row for the legacy variant of an A/B decision.

    No-op when ``organization_id`` is missing (column is NOT NULL) or when
    no DB factory is available.
    """

    if organization_id is None:
        return None
    factory = get_session_factory()
    if factory is None:
        return None
    try:
        with factory() as session:
            row = LearningLog(
                organization_id=int(organization_id),
                user_id=int(user_id) if user_id is not None else None,
                source_type="legacy_brain",
                action_type=str(action_type or "")[:128],
                outcome="decision_pending",
                lesson_summary=" | ".join(reasoning)[:4000],
                context={"intent": intent, "domain": domain},
                input_data_json={"decision": decision_payload or {}},
                outcome_json={
                    "action": action,
                    "confidence": float(confidence),
                    "expected_reward": 0.0,
                    "raw_ok": bool(raw.get("ok")),
                    "validation_error": raw.get("validation_error"),
                    "safety_error": raw.get("safety_error"),
                    "decided_at": timestamp.isoformat(),
                },
                result={"phase": "decided"},
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return int(row.id)
    except Exception as exc:
        _LOG.warning("legacy_brain._log_decision failed: %s", exc)
        return None


def _legacy_record_outcome(
    learning_log_id: int | None,
    outcome: dict[str, Any],
    reward: float,
) -> None:
    if not learning_log_id:
        return
    factory = get_session_factory()
    if factory is None:
        return
    try:
        with factory() as session:
            row = session.get(LearningLog, int(learning_log_id))
            if row is None or row.source_type != "legacy_brain":
                return
            outcome_json = dict(row.outcome_json or {})
            outcome_json.update(
                {
                    "actual": dict(outcome or {}),
                    "reward": float(reward),
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            row.outcome_json = outcome_json
            row.outcome = "outcome_recorded"
            row.success = bool(reward > 0)
            row.result = {"phase": "resolved", "reward": float(reward)}
            session.commit()
    except Exception as exc:
        _LOG.warning("legacy_brain._record_outcome failed: %s", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


_decision_brain_v2: DecisionBrainV2 | None = None
_decision_brain_v2_lock = threading.Lock()


def get_decision_brain_v2() -> DecisionBrainV2:
    global _decision_brain_v2
    if _decision_brain_v2 is None:
        with _decision_brain_v2_lock:
            if _decision_brain_v2 is None:
                _decision_brain_v2 = DecisionBrainV2()
    return _decision_brain_v2


def reset_decision_brain_v2() -> None:
    """Test-only: drop the singleton so env-flag changes can take effect."""

    global _decision_brain_v2
    with _decision_brain_v2_lock:
        _decision_brain_v2 = None


__all__ = [
    "DecisionBrainV2",
    "get_decision_brain_v2",
    "reset_decision_brain_v2",
]
