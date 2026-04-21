"""Group plan steps into dependency-depth waves for optional parallel shell execution."""

from __future__ import annotations

from typing import Any


def _depth(tid: int, id_to_task: dict[int, dict[str, Any]], memo: dict[int, int]) -> int:
    if tid in memo:
        return memo[tid]
    task = id_to_task.get(tid)
    if task is None:
        memo[tid] = 0
        return 0
    deps_raw = task.get("depends_on") or []
    deps: list[int] = []
    for d in deps_raw:
        try:
            di = int(d)
        except (TypeError, ValueError):
            continue
        if di in id_to_task:
            deps.append(di)
    if not deps:
        memo[tid] = 0
        return 0
    memo[tid] = 1 + max(_depth(d, id_to_task, memo) for d in deps)
    return memo[tid]


def tasks_to_waves(tasks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """
    Topological depth grouping: tasks at the same depth may run in parallel if independent
    and marked parallel-safe (caller validates).
    """
    if not tasks:
        return []
    id_to_task: dict[int, dict[str, Any]] = {}
    for t in tasks:
        try:
            tid = int(t.get("id", 0))
        except (TypeError, ValueError):
            continue
        id_to_task[tid] = t
    memo: dict[int, int] = {}
    by_level: dict[int, list[dict[str, Any]]] = {}
    for tid, t in id_to_task.items():
        d = _depth(tid, id_to_task, memo)
        by_level.setdefault(d, []).append(t)
    for lv in by_level:
        by_level[lv].sort(key=lambda x: (int(x.get("priority", 3)), int(x.get("id", 0))))
    return [by_level[k] for k in sorted(by_level.keys())]


def wave_eligible_for_parallel_shell(wave: list[dict[str, Any]]) -> bool:
    """True if every task can be executed as an isolated shell command (audit + command)."""
    if len(wave) < 2:
        return False
    for t in wave:
        if not t.get("parallel_safe"):
            return False
        if str(t.get("type", "")).lower() != "audit":
            return False
        if not str(t.get("command", "")).strip():
            return False
        if str(t.get("risk_level", "low")).lower() == "high":
            return False
    return True
