"""
Thin wrapper around ``ThreadPoolExecutor`` for parallel independent work (phase 9).

Default Jarvis autonomy remains sequential; use only when tasks are isolated (e.g. pure HTTP probes).
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable


class LightQueue:
    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max(1, int(max_workers)), thread_name_prefix="thiramai-q")

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]:
        return self._pool.submit(fn, *args, **kwargs)

    def shutdown(self, *, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)
