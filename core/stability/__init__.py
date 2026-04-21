"""
Intelligent stability layer: circuit breaker, backoff+jitter retries, resource hints,
failure memory, task priority, and safe-mode escalation.

Optional dependency: ``psutil`` for richer CPU/memory (install separately; stdlib fallback used).
"""

from __future__ import annotations

from core.stability.auto_fix_guard import AutoFixGuard
from core.stability.circuit_breaker import CircuitBreaker, get_circuit_breaker
from core.stability.escalation import maybe_escalate_incident_mode
from core.stability.failure_memory import FailureMemory, get_failure_memory
from core.stability.logging_tags import log_auto_fix_blocked, log_circuit, log_resource, log_stability
from core.stability.resource_monitor import ResourceMonitor, get_resource_monitor
from core.stability.retry import backoff_delay_seconds, http_get_with_stability
from core.stability.task_priority import TaskPriority, should_run_priority

__all__ = [
    "AutoFixGuard",
    "CircuitBreaker",
    "FailureMemory",
    "ResourceMonitor",
    "TaskPriority",
    "backoff_delay_seconds",
    "get_circuit_breaker",
    "get_failure_memory",
    "get_resource_monitor",
    "http_get_with_stability",
    "log_auto_fix_blocked",
    "log_circuit",
    "log_resource",
    "log_stability",
    "maybe_escalate_incident_mode",
    "should_run_priority",
]
