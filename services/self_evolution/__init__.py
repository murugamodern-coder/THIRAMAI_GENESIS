"""Closed-loop self-improvement: monitor regressions, propose fixes, gate deploy."""

from services.self_evolution.improvement_generator import (
    ImprovementGenerator,
    ImprovementHypothesis,
    get_improvement_generator,
    reset_improvement_generator,
)
from services.self_evolution.improvement_loop import (
    IterationResult,
    SelfImprovementLoop,
    get_improvement_loop,
    reset_improvement_loop,
    reset_self_evolution_singletons,
)
from services.self_evolution.performance_monitor import (
    PerformanceDegradation,
    PerformanceMetrics,
    PerformanceMonitor,
    get_performance_monitor,
    reset_performance_monitor,
)

__all__ = [
    "ImprovementGenerator",
    "ImprovementHypothesis",
    "IterationResult",
    "PerformanceDegradation",
    "PerformanceMetrics",
    "PerformanceMonitor",
    "SelfImprovementLoop",
    "get_improvement_generator",
    "get_improvement_loop",
    "get_performance_monitor",
    "reset_improvement_generator",
    "reset_improvement_loop",
    "reset_performance_monitor",
    "reset_self_evolution_singletons",
]
