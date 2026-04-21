"""Track repeated failures per module/key and suggest degraded strategies."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Literal

Strategy = Literal["retry", "skip", "degrade"]


@dataclass
class FailureRecord:
    count: int = 0
    last_ts: float = 0.0
    last_error: str = ""
    strategy: Strategy = "retry"


class FailureMemory:
    """
    Keyed by ``module:key`` (e.g. ``startup:bundle_integrity``).
    After *repeat_threshold* similar failures, strategy becomes *degrade* or *skip*.
    """

    def __init__(self) -> None:
        self._data: dict[str, FailureRecord] = {}
        self._lock = threading.Lock()
        self._repeat_threshold = int(os.environ.get("THIRAMAI_STABILITY_FAILURE_REPEAT_THRESHOLD", "5") or "5")
        self._repeat_threshold = max(2, self._repeat_threshold)

    def record(self, module: str, key: str, error_detail: str = "") -> Strategy:
        composite = f"{module}:{key}"
        with self._lock:
            rec = self._data.get(composite)
            if rec is None:
                rec = FailureRecord()
                self._data[composite] = rec
            rec.count += 1
            rec.last_ts = time.time()
            rec.last_error = (error_detail or "")[:500]

            if rec.count >= self._repeat_threshold * 2:
                rec.strategy = "skip"
            elif rec.count >= self._repeat_threshold:
                rec.strategy = "degrade"
            else:
                rec.strategy = "retry"
            return rec.strategy

    def strategy_for(self, module: str, key: str) -> Strategy:
        composite = f"{module}:{key}"
        with self._lock:
            rec = self._data.get(composite)
            if rec is None:
                return "retry"
            return rec.strategy

    def reset_key(self, module: str, key: str) -> None:
        composite = f"{module}:{key}"
        with self._lock:
            self._data.pop(composite, None)

    def get_count(self, module: str, key: str) -> int:
        composite = f"{module}:{key}"
        with self._lock:
            rec = self._data.get(composite)
            return rec.count if rec else 0


_memory: FailureMemory | None = None
_mem_lock = threading.Lock()


def get_failure_memory() -> FailureMemory:
    global _memory
    with _mem_lock:
        if _memory is None:
            _memory = FailureMemory()
        return _memory
