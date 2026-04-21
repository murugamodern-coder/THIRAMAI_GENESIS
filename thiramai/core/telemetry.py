from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SessionTelemetry:
    total_commands_executed: int = 0
    total_policy_blocks: int = 0
    total_successful_commands: int = 0
    avg_llm_confidence: float = 0.0
    total_human_interventions: int = 0
    current_goal: str = ""
    current_cycle_id: int = 0
    current_task: str = "idle"
    last_blocked_reason: str = ""
    last_cycle_time_sec: float = 0.0
    avg_cycle_time_sec: float = 0.0
    _cycle_count: int = 0
    _cycle_time_sum: float = 0.0
    _llm_confidence_count: int = 0
    _llm_confidence_sum: float = 0.0

    def record_execution(self, *, executed: bool, blocked: bool, status: str = "", blocked_reason: str = "") -> None:
        if executed:
            self.total_commands_executed += 1
            if str(status).lower() == "success":
                self.total_successful_commands += 1
        if blocked:
            self.total_policy_blocks += 1
            self.last_blocked_reason = str(blocked_reason or self.last_blocked_reason)

    def record_llm_confidence(self, confidence: float | int | None) -> None:
        if confidence is None:
            return
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            return
        value = max(0.0, min(1.0, value))
        self._llm_confidence_sum += value
        self._llm_confidence_count += 1
        self.avg_llm_confidence = self._llm_confidence_sum / float(self._llm_confidence_count)

    def record_human_intervention(self) -> None:
        self.total_human_interventions += 1

    def record_cycle_time(self, elapsed_seconds: float | int) -> None:
        try:
            value = float(elapsed_seconds)
        except (TypeError, ValueError):
            return
        value = max(0.0, value)
        self.last_cycle_time_sec = value
        self._cycle_time_sum += value
        self._cycle_count += 1
        self.avg_cycle_time_sec = self._cycle_time_sum / float(self._cycle_count)

    def success_rate(self) -> float:
        if self.total_commands_executed <= 0:
            return 0.0
        return (float(self.total_successful_commands) / float(self.total_commands_executed)) * 100.0

    def safety_score(self) -> float:
        if self.total_commands_executed <= 0:
            return 0.0
        # Requested metric: policy blocks vs total commands.
        return (float(self.total_policy_blocks) / float(self.total_commands_executed)) * 100.0

    def set_runtime_status(self, *, goal: str, cycle_id: int, task: str) -> None:
        self.current_goal = str(goal)
        self.current_cycle_id = int(cycle_id)
        self.current_task = str(task)
