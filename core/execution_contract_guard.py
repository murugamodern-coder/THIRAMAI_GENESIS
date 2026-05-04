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
    """Bind ``run_id`` to the current ContextVar scope.

    Historically this function also reset ``_pipeline_stages`` to ``[]``.
    That was wrong: the brain pipeline marks ``brain_execute`` and
    ``preflight`` *before* a run id is created (they run as part of
    planning), and only calls ``activate_execution_context`` once
    ``run_persisted_action_plan`` is about to start. Wiping the list here
    deleted those earlier marks, so ``assert_pipeline_sequence`` always
    saw only ``execute_action_plan / closure / retry_learning`` and
    raised ``pipeline_missing_stages:brain_execute,preflight,...``.

    Per-call isolation is now the sole responsibility of
    ``clear_execution_context``, which the brain entrypoint already
    invokes in a ``finally`` block. Each fresh request starts with the
    ContextVar default ``[]`` (or the previous-call clear), accumulates
    the five required marks, asserts the order, and clears.
    """
    rid = int(run_id)
    if rid <= 0:
        raise ExecutionContractViolation("execution_context_requires_positive_run_id")
    _current_run_id.set(rid)
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

