"""Classify work so optional tasks defer when the host is under load."""

from __future__ import annotations

import os
from enum import IntEnum

from core.stability.resource_monitor import ResourceMonitor, get_resource_monitor, is_overloaded


class TaskPriority(IntEnum):
    CRITICAL = 0
    NORMAL = 1
    OPTIONAL = 2


def should_run_priority(
    priority: TaskPriority,
    monitor: ResourceMonitor | None = None,
) -> bool:
    """
    Critical always runs. Optional is skipped when overloaded (configurable thresholds).
    Normal runs unless *very* overloaded (optional stricter via env).
    """
    if priority == TaskPriority.CRITICAL:
        return True
    m = monitor or get_resource_monitor()
    snap = m.snapshot()
    if not is_overloaded(snap):
        return True
    if priority == TaskPriority.OPTIONAL:
        return _truthy("THIRAMAI_STABILITY_RUN_OPTIONAL_WHEN_OVERLOADED", default=False)
    if priority == TaskPriority.NORMAL:
        return _truthy("THIRAMAI_STABILITY_RUN_NORMAL_WHEN_OVERLOADED", default=True)
    return True


def _truthy(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")
