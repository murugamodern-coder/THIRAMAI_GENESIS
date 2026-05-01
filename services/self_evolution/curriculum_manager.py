"""
Curriculum learning: schedule tasks easy → hard with explicit mastery gates.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from services.self_evolution.meta_learner import Task

logger = logging.getLogger(__name__)


@dataclass
class CurriculumStage:
    """One difficulty band in the curriculum."""

    stage_id: int
    difficulty_range: tuple[float, float]
    tasks: list[Task] = field(default_factory=list)
    mastery_threshold: float = 0.75


@dataclass
class LearningProgress:
    """Snapshot after recording a result."""

    current_stage: int
    total_stages: int
    tasks_attempted: int
    tasks_mastered: int
    current_success_rate: float
    avg_adaptation_time_ms: float
    ready_to_advance: bool
    timestamp: datetime


class CurriculumManager:
    """
    Bucket tasks by difficulty, serve the current stage, and advance when
    aggregate mastery crosses the stage threshold.
    """

    def __init__(self, *, min_attempts_per_stage: int = 1) -> None:
        self.stages: list[CurriculumStage] = self._initialize_stages()
        self.current_stage_idx = 0
        self.stage_history: list[LearningProgress] = []
        self.min_attempts_per_stage = max(1, int(min_attempts_per_stage))
        self._task_stats: dict[str, dict[str, int]] = {}
        self._adapt_times: list[float] = []

    def _initialize_stages(self) -> list[CurriculumStage]:
        return [
            CurriculumStage(stage_id=1, difficulty_range=(0.0, 0.3), mastery_threshold=0.80),
            CurriculumStage(stage_id=2, difficulty_range=(0.3, 0.6), mastery_threshold=0.75),
            CurriculumStage(stage_id=3, difficulty_range=(0.6, 0.8), mastery_threshold=0.70),
            CurriculumStage(stage_id=4, difficulty_range=(0.8, 1.0), mastery_threshold=0.65),
        ]

    def _stage_index_for_difficulty(self, d: float) -> int:
        x = float(d)
        for i, st in enumerate(self.stages):
            lo, hi = st.difficulty_range
            last = i == len(self.stages) - 1
            if last:
                if lo <= x <= hi:
                    return i
            elif lo <= x < hi:
                return i
        return len(self.stages) - 1

    def add_task(self, task: Task) -> None:
        idx = self._stage_index_for_difficulty(task.difficulty)
        self.stages[idx].tasks.append(task)
        logger.info(
            "curriculum: task %s → stage %s (difficulty=%.3f)",
            task.task_id,
            self.stages[idx].stage_id,
            task.difficulty,
        )

    def get_current_task(self) -> Task | None:
        stage = self.stages[self.current_stage_idx]
        if not stage.tasks:
            return None
        thr = stage.mastery_threshold
        for t in stage.tasks:
            st = self._task_stats.get(t.task_id)
            if st is None:
                return t
            ta, ts = int(st["attempts"]), int(st["successes"])
            if ta == 0 or (ts / ta) < thr:
                return t
        return stage.tasks[0]

    def record_result(self, task: Task, success: bool, adaptation_time_ms: float) -> LearningProgress:
        stage = self.stages[self.current_stage_idx]
        st = self._task_stats.setdefault(task.task_id, {"attempts": 0, "successes": 0})
        st["attempts"] += 1
        if success:
            st["successes"] += 1
        self._adapt_times.append(float(adaptation_time_ms))
        avg_ms = float(sum(self._adapt_times) / max(len(self._adapt_times), 1))

        attempted = 0
        mastered = 0
        ratios: list[float] = []
        enough_attempts = True
        for t in stage.tasks:
            r = self._task_stats.get(t.task_id, {"attempts": 0, "successes": 0})
            ta, ts = int(r["attempts"]), int(r["successes"])
            attempted += ta
            if ta < self.min_attempts_per_stage:
                enough_attempts = False
            if ta > 0:
                ratios.append(ts / ta)
            if ta > 0 and (ts / ta) >= stage.mastery_threshold:
                mastered += 1

        success_rate = float(sum(ratios) / len(ratios)) if ratios else 0.0
        ready = (
            bool(stage.tasks)
            and enough_attempts
            and len(ratios) == len(stage.tasks)
            and success_rate >= stage.mastery_threshold
        )

        progress = LearningProgress(
            current_stage=self.current_stage_idx + 1,
            total_stages=len(self.stages),
            tasks_attempted=attempted,
            tasks_mastered=mastered,
            current_success_rate=float(success_rate),
            avg_adaptation_time_ms=avg_ms,
            ready_to_advance=ready,
            timestamp=datetime.now(timezone.utc),
        )
        self.stage_history.append(progress)
        logger.info(
            "curriculum: stage %s/%s success_rate=%.2f ready=%s",
            progress.current_stage,
            progress.total_stages,
            success_rate,
            ready,
        )
        return progress

    def advance_stage(self) -> bool:
        if self.current_stage_idx >= len(self.stages) - 1:
            logger.info("curriculum: already at final stage")
            return False
        last = self.stage_history[-1] if self.stage_history else None
        if last is not None and last.ready_to_advance:
            self.current_stage_idx += 1
            self._adapt_times.clear()
            logger.info("curriculum: advanced to stage %s", self.current_stage_idx + 1)
            return True
        return False

    def get_progress(self) -> LearningProgress | None:
        return self.stage_history[-1] if self.stage_history else None

    def reset_stage_stats(self) -> None:
        """Test helper: clear per-task counters (keep tasks in stages)."""
        self._task_stats.clear()
        self._adapt_times.clear()
        self.stage_history.clear()


_curriculum_manager: CurriculumManager | None = None
_curriculum_lock = threading.Lock()


def get_curriculum_manager() -> CurriculumManager:
    global _curriculum_manager
    if _curriculum_manager is None:
        with _curriculum_lock:
            if _curriculum_manager is None:
                _curriculum_manager = CurriculumManager()
    return _curriculum_manager


def reset_curriculum_manager() -> None:
    global _curriculum_manager
    with _curriculum_lock:
        _curriculum_manager = None


__all__ = [
    "CurriculumManager",
    "CurriculumStage",
    "LearningProgress",
    "get_curriculum_manager",
    "reset_curriculum_manager",
]
