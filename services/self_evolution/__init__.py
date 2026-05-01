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
from services.self_evolution.feature_engineer import (
    AutoFeatureEngineer,
    get_feature_engineer,
    reset_feature_engineer,
)
from services.self_evolution.hyperparameter_optimizer import (
    BayesianOptimizer,
    HyperparameterSpace,
    HyperparameterTuner,
    LightweightNAS,
    LightweightNASResult,
    TrialResult,
    get_hyperparameter_tuner,
    reset_hyperparameter_tuner,
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
from services.self_evolution.tool_discovery import (
    DiscoveredTool,
    ToolDiscovery,
    ToolUsagePattern,
    get_tool_discovery,
    reset_tool_discovery,
)

__all__ = [
    "AutoFeatureEngineer",
    "BayesianOptimizer",
    "CurriculumManager",
    "CurriculumStage",
    "DiscoveredTool",
    "HyperparameterSpace",
    "HyperparameterTuner",
    "ImprovementGenerator",
    "ImprovementHypothesis",
    "IterationResult",
    "LearningProgress",
    "LightweightNAS",
    "LightweightNASResult",
    "MAML",
    "MetaLearner",
    "MetaLearningResult",
    "PerformanceDegradation",
    "PerformanceMetrics",
    "PerformanceMonitor",
    "SelfImprovementLoop",
    "Task",
    "ToolDiscovery",
    "ToolUsagePattern",
    "TrialResult",
    "get_curriculum_manager",
    "get_feature_engineer",
    "get_hyperparameter_tuner",
    "get_improvement_generator",
    "get_improvement_loop",
    "get_meta_learner",
    "get_performance_monitor",
    "get_tool_discovery",
    "online_learner_meta_context",
    "reset_curriculum_manager",
    "reset_feature_engineer",
    "reset_hyperparameter_tuner",
    "reset_improvement_generator",
    "reset_improvement_loop",
    "reset_meta_learner",
    "reset_performance_monitor",
    "reset_self_evolution_singletons",
    "reset_tool_discovery",
]
