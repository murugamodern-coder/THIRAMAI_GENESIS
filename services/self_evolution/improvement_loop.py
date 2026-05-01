"""Closed-loop self-improvement orchestration.

Pipeline (observe → hypothesize → propose → *human gate* → deploy):

1. :class:`PerformanceMonitor` samples **paired** time windows.
2. :class:`ImprovementGenerator` proposes fixes (LLM or rule fallback).
3. This module records proposals; **no automatic prod deploy** occurs.
   Downstream automation should enforce owner / ops approval (see
   ``deployment_requires_approval``).

The blocking :meth:`SelfImprovementLoop.start` exists for long-running
workers only — unit tests and orchestrators should call
:meth:`run_iteration` instead.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.self_evolution.curriculum_manager import reset_curriculum_manager
from services.self_evolution.improvement_generator import (
    ImprovementGenerator,
    ImprovementHypothesis,
    get_improvement_generator,
    reset_improvement_generator,
)
from services.self_evolution.meta_learner import reset_meta_learner
from services.self_evolution.performance_monitor import (
    PerformanceMetrics,
    PerformanceMonitor,
    get_performance_monitor,
    reset_performance_monitor,
)

logger = logging.getLogger(__name__)


@dataclass
class IterationResult:
    """Structured output of one monitoring cycle."""

    started_at: datetime
    finished_at: datetime
    current_metrics: PerformanceMetrics
    degradations: list[Any] = field(default_factory=list)
    hypotheses: list[ImprovementHypothesis] = field(default_factory=list)
    deployment: dict[str, Any] = field(default_factory=dict)
    online_learner_probe: dict[str, Any] = field(default_factory=dict)


class SelfImprovementLoop:
    def __init__(
        self,
        check_interval_hours: int = 24,
        *,
        monitor: PerformanceMonitor | None = None,
        generator: ImprovementGenerator | None = None,
        deployment_requires_approval: bool = True,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.check_interval_hours = max(1, int(check_interval_hours))
        self.monitor = monitor or get_performance_monitor()
        self.generator = generator or get_improvement_generator()
        self.deployment_requires_approval = bool(deployment_requires_approval)
        self._sleep = sleep_fn or time.sleep
        self.is_running = False

    def start(self) -> None:
        """Blocking supervisor loop (daemon/worker entry point)."""
        logger.info("self_improvement_loop: starting (interval=%sh)", self.check_interval_hours)
        self.is_running = True
        while self.is_running:
            try:
                self.run_iteration()
            except Exception as exc:
                logger.error("self_improvement_loop: iteration failed: %s", exc, exc_info=True)
                self._sleep(3600.0)
                continue
            if not self.is_running:
                break
            self._sleep(float(self.check_interval_hours * 3600))

    def stop(self) -> None:
        self.is_running = False

    def run_iteration(self, *, window_hours: int = 24) -> IterationResult:
        """Run a single monitor → detect → hypothesize → propose (!deploy) cycle."""
        t0 = datetime.now(timezone.utc)
        current, degradations = self.monitor.check_performance(window_hours=window_hours)
        logger.info(
            "self_improvement_loop: accuracy=%.2f%% error_rate=%.4f sample=%d",
            current.decision_accuracy * 100,
            current.error_rate,
            current.sample_size,
        )
        hypotheses: list[ImprovementHypothesis] = []
        if degradations:
            logger.warning("self_improvement_loop: %d degradation(s)", len(degradations))
            hypotheses = self.generator.generate_fixes(degradations)

        deployment = self._build_deployment_plan(hypotheses)
        online_probe = self._probe_online_learner()

        result = IterationResult(
            started_at=t0,
            finished_at=datetime.now(timezone.utc),
            current_metrics=current,
            degradations=degradations,
            hypotheses=hypotheses,
            deployment=deployment,
            online_learner_probe=online_probe,
        )
        logger.info(
            "self_improvement_loop: iteration done (hypotheses=%d)",
            len(hypotheses),
        )
        return result

    def _build_deployment_plan(self, hypotheses: list[ImprovementHypothesis]) -> dict[str, Any]:
        if not hypotheses:
            return {"status": "noop", "reason": "no_hypotheses"}
        plan = {
            "status": "pending_owner_approval" if self.deployment_requires_approval else "ready_for_ci",
            "count": len(hypotheses),
            "hypothesis_ids": [h.hypothesis_id for h in hypotheses],
            "recommended_test_strategies": sorted({h.test_strategy for h in hypotheses}),
            "note": "No production mutation from SelfImprovementLoop — integrate with CI / feature flags.",
        }
        return plan

    def _probe_online_learner(self) -> dict[str, Any]:
        """Read-only capability check; does not train or write."""
        try:
            from services.ml import online_learner

            return {
                "online_learner_importable": True,
                "online_available": bool(online_learner.online_available()),
                "hint": "Wire resolve_pending / partial_fit from an approved job after A/B win.",
            }
        except Exception as exc:
            return {
                "online_learner_importable": False,
                "error": str(exc),
            }


_singleton: SelfImprovementLoop | None = None
_singleton_lock = threading.Lock()


def get_improvement_loop(**kwargs: Any) -> SelfImprovementLoop:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = SelfImprovementLoop(**kwargs)
    return _singleton


def reset_improvement_loop() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None


def reset_self_evolution_singletons() -> None:
    """Test helper: clears monitor + generator + loop + meta/curriculum singletons."""
    reset_improvement_loop()
    reset_improvement_generator()
    reset_performance_monitor()
    reset_meta_learner()
    reset_curriculum_manager()


__all__ = [
    "IterationResult",
    "SelfImprovementLoop",
    "get_improvement_loop",
    "reset_improvement_loop",
    "reset_self_evolution_singletons",
]
