"""Approximate CPU/memory/thread load for deferring optional work (stdlib + optional psutil)."""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass

from core.stability.logging_tags import log_resource

try:
    import psutil  # type: ignore[import-untyped]

    _HAS_PSUTIL = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    _HAS_PSUTIL = False


@dataclass
class ResourceSnapshot:
    cpu_percent: float | None
    memory_mb: float | None
    threads: int
    tracked_tasks: int


_task_counter = 0
_task_lock = threading.Lock()


def increment_tracked_tasks(delta: int = 1) -> None:
    global _task_counter
    with _task_lock:
        _task_counter = max(0, _task_counter + delta)


def get_tracked_tasks() -> int:
    with _task_lock:
        return _task_counter


def snapshot() -> ResourceSnapshot:
    threads = threading.active_count()
    cpu: float | None = None
    mem_mb: float | None = None

    if _HAS_PSUTIL and psutil is not None:
        try:
            p = psutil.Process()
            cpu = p.cpu_percent(interval=None)
            mem_mb = p.memory_info().rss / (1024 * 1024)
        except (OSError, AttributeError):
            pass
    else:
        try:
            import resource

            ru = resource.getrusage(resource.RUSAGE_SELF)
            if sys.platform == "darwin":
                mem_mb = ru.ru_maxrss / (1024 * 1024)
            else:
                mem_mb = ru.ru_maxrss / 1024.0
        except (ImportError, OSError, ValueError):
            mem_mb = None

    return ResourceSnapshot(
        cpu_percent=cpu,
        memory_mb=mem_mb,
        threads=threads,
        tracked_tasks=get_tracked_tasks(),
    )


def is_overloaded(
    snap: ResourceSnapshot | None = None,
    *,
    cpu_threshold: float | None = None,
    memory_mb_threshold: float | None = None,
    thread_threshold: int | None = None,
) -> bool:
    """
    Returns True if any configured threshold is exceeded.
    Unset thresholds are ignored (env-driven defaults).
    """
    s = snap or snapshot()
    cpu_t = cpu_threshold
    mem_t = memory_mb_threshold
    thr_t = thread_threshold
    if cpu_t is None:
        raw = os.environ.get("THIRAMAI_STABILITY_CPU_PERCENT")
        cpu_t = float(raw) if raw and raw.strip() else None
    if mem_t is None:
        raw = os.environ.get("THIRAMAI_STABILITY_MEMORY_MB")
        mem_t = float(raw) if raw and raw.strip() else None
    if thr_t is None:
        raw = os.environ.get("THIRAMAI_STABILITY_THREAD_THRESHOLD")
        thr_t = int(raw) if raw and raw.strip() else None

    reasons: list[str] = []
    if cpu_t is not None and s.cpu_percent is not None and s.cpu_percent > cpu_t:
        reasons.append(f"cpu {s.cpu_percent:.1f}% > {cpu_t}%")
    if mem_t is not None and s.memory_mb is not None and s.memory_mb > mem_t:
        reasons.append(f"rss {s.memory_mb:.0f}MB > {mem_t}MB")
    if thr_t is not None and s.threads > thr_t:
        reasons.append(f"threads {s.threads} > {thr_t}")

    if reasons:
        log_resource("; ".join(reasons))
        return True
    return False


class ResourceMonitor:
    """Thin wrapper for tests and optional future polling."""

    def snapshot(self) -> ResourceSnapshot:
        return snapshot()

    def overloaded(self) -> bool:
        return is_overloaded()


_global: ResourceMonitor | None = None


def get_resource_monitor() -> ResourceMonitor:
    global _global
    if _global is None:
        _global = ResourceMonitor()
    return _global


def _cpu_poll_loop() -> None:
    """Optional background thread: sample CPU with short interval so cpu_percent is meaningful."""
    if not _HAS_PSUTIL or psutil is None:
        return
    try:
        p = psutil.Process()
        while True:
            time.sleep(float(os.environ.get("THIRAMAI_STABILITY_RESOURCE_POLL_SEC", "30") or "30"))
            if is_overloaded():
                log_resource("overload still active (poll)")
    except Exception:
        return


def start_optional_resource_poll() -> None:
    """If THIRAMAI_STABILITY_RESOURCE_POLL_SEC > 0, start daemon poll (best-effort)."""
    sec = float(os.environ.get("THIRAMAI_STABILITY_RESOURCE_POLL_SEC", "0") or "0")
    if sec <= 0 or not _HAS_PSUTIL:
        return
    t = threading.Thread(target=_cpu_poll_loop, name="thiramai-resource-poll", daemon=True)
    t.start()
