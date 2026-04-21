"""Structured console tags for stability observability."""

from __future__ import annotations

import logging

_logger = logging.getLogger("thiramai.stability")


def log_stability(message: str) -> None:
    print(f"[STABILITY] {message}", flush=True)
    _logger.info("[STABILITY] %s", message)


def log_circuit(message: str) -> None:
    print(f"[CIRCUIT BREAKER] {message}", flush=True)
    _logger.warning("[CIRCUIT BREAKER] %s", message)


def log_auto_fix_blocked(message: str) -> None:
    print(f"[AUTO-FIX BLOCKED] {message}", flush=True)
    _logger.warning("[AUTO-FIX BLOCKED] %s", message)


def log_resource(message: str) -> None:
    print(f"[RESOURCE LIMIT] {message}", flush=True)
    _logger.warning("[RESOURCE LIMIT] %s", message)
