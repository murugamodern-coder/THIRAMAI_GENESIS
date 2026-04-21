"""Thread-safe TTL cache for repeated planner / tool prompts (phase 9)."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Hashable, TypeVar

T = TypeVar("T")


class TTLCache:
    def __init__(self, ttl_seconds: float = 120.0, max_items: int = 512) -> None:
        self._ttl = max(1.0, float(ttl_seconds))
        self._max = max(16, int(max_items))
        self._data: dict[Hashable, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Any | None:
        now = time.monotonic()
        with self._lock:
            row = self._data.get(key)
            if row is None:
                return None
            exp, val = row
            if now > exp:
                del self._data[key]
                return None
            return val

    def set(self, key: Hashable, value: Any) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._data) >= self._max:
                # Drop arbitrary oldest bucket (simple bounded cache).
                drop = next(iter(self._data.keys()))
                del self._data[drop]
            self._data[key] = (now + self._ttl, value)

    def get_or_set(self, key: Hashable, factory: Callable[[], T]) -> T:
        hit = self.get(key)
        if hit is not None:
            return hit  # type: ignore[return-value]
        val = factory()
        self.set(key, val)
        return val
