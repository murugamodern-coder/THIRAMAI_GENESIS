"""Global execution contract enforcement for side-effect pathways."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

_current_run_id: ContextVar[int | None] = ContextVar("thiramai_execution_run_id", default=None)
_pipeline_stages: ContextVar[list[str]] = ContextVar("thiramai_pipeline_stages", default=[])


class ExecutionContractViolation(RuntimeError):
    """Raised when side effects occur outside enforced execution context."""


class PipelineViolationError(RuntimeError):
    """Raised when required pipeline stages are skipped or out of order."""


@dataclass
class ExecutionContractContext:
    run_id: int


def activate_execution_context(run_id: int) -> ExecutionContractContext:
    rid = int(run_id)
    if rid <= 0:
        raise ExecutionContractViolation("execution_context_requires_positive_run_id")
    _current_run_id.set(rid)
    _pipeline_stages.set([])
    return ExecutionContractContext(run_id=rid)


def clear_execution_context() -> None:
    _current_run_id.set(None)
    _pipeline_stages.set([])


def current_run_id() -> int | None:
    return _current_run_id.get()


def assert_execution_context(required_run: bool = True) -> int | None:
    rid = _current_run_id.get()
    if required_run and (rid is None or int(rid) <= 0):
        raise ExecutionContractViolation("side_effect_without_execution_run_context")
    return rid


def mark_pipeline_stage(stage: str) -> None:
    s = str(stage or "").strip().lower()
    if not s:
        return
    cur = list(_pipeline_stages.get() or [])
    cur.append(s)
    _pipeline_stages.set(cur)


def assert_pipeline_sequence() -> None:
    required = ["brain_execute", "preflight", "execute_action_plan", "closure", "retry_learning"]
    seen = list(_pipeline_stages.get() or [])
    cursor = 0
    for stage in seen:
        if cursor < len(required) and stage == required[cursor]:
            cursor += 1
    if cursor < len(required):
        missing = required[cursor:]
        raise PipelineViolationError(f"pipeline_missing_stages:{','.join(missing)}")

