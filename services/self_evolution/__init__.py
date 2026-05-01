"""Closed-loop self-improvement: monitor regressions, propose fixes, gate deploy."""

from services.self_evolution.curriculum_manager import (
    CurriculumManager,
    CurriculumStage,
    LearningProgress,
    get_curriculum_manager,
    reset_curriculum_manager,
)
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
from services.self_evolution.meta_learner import (
    MAML,
    MetaLearner,
    MetaLearningResult,
    Task,
    get_meta_learner,
    online_learner_meta_context,
    reset_meta_learner,
)
from services.self_evolution.performance_monitor import (
    PerformanceDegradation,
    PerformanceMetrics,
    PerformanceMonitor,
    get_performance_monitor,
    reset_performance_monitor,
)

__all__ = [
    "CurriculumManager",
    "CurriculumStage",
    "ImprovementGenerator",
    "ImprovementHypothesis",
    "IterationResult",
    "LearningProgress",
    "MAML",
    "MetaLearner",
    "MetaLearningResult",
    "PerformanceDegradation",
    "PerformanceMetrics",
    "PerformanceMonitor",
    "SelfImprovementLoop",
    "Task",
    "get_curriculum_manager",
    "get_improvement_generator",
    "get_improvement_loop",
    "get_meta_learner",
    "get_performance_monitor",
    "online_learner_meta_context",
    "reset_curriculum_manager",
    "reset_improvement_generator",
    "reset_improvement_loop",
    "reset_meta_learner",
    "reset_performance_monitor",
    "reset_self_evolution_singletons",
]
