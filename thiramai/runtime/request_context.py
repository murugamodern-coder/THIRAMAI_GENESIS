"""Async-safe tenant context for goal execution (LLM quota attribution)."""

from __future__ import annotations

import contextlib
import contextvars
from typing import Iterator

_goal_org: contextvars.ContextVar[int | None] = contextvars.ContextVar("goal_org", default=None)
_goal_user: contextvars.ContextVar[int | None] = contextvars.ContextVar("goal_user", default=None)
_goal_job: contextvars.ContextVar[str | None] = contextvars.ContextVar("goal_job", default=None)


def get_goal_tenant() -> tuple[int | None, int | None, str | None]:
    return _goal_org.get(), _goal_user.get(), _goal_job.get()


@contextlib.contextmanager
def goal_execution_context(organization_id: int, user_id: int, job_id: str) -> Iterator[None]:
    tok_o = _goal_org.set(int(organization_id))
    tok_u = _goal_user.set(int(user_id))
    tok_j = _goal_job.set(job_id)
    try:
        yield
    finally:
        _goal_org.reset(tok_o)
        _goal_user.reset(tok_u)
        _goal_job.reset(tok_j)
