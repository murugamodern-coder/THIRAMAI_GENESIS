"""Exponential backoff with jitter for resilient HTTP and generic retries."""

from __future__ import annotations

import random
import time
import urllib.error
import urllib.request
from typing import Callable, TypeVar

T = TypeVar("T")


def backoff_delay_seconds(
    attempt_index: int,
    *,
    base_sec: float = 0.15,
    max_sec: float = 30.0,
    jitter_ratio: float = 0.25,
) -> float:
    """
    *attempt_index* is 0-based. Delay = min(max_sec, base * 2^attempt) + random jitter.
    """
    raw = min(max_sec, base_sec * (2**attempt_index))
    jitter = raw * jitter_ratio * random.random()
    return raw + jitter


def sleep_backoff(attempt_index: int, **kwargs: float) -> None:
    time.sleep(backoff_delay_seconds(attempt_index, **kwargs))


def http_get_with_stability(
    url: str,
    *,
    timeout_sec: float = 3.0,
    max_attempts: int = 3,
    base_sec: float = 0.15,
    max_backoff_sec: float = 8.0,
    jitter_ratio: float = 0.25,
    on_attempt: Callable[[int, str], None] | None = None,
) -> tuple[bool, str]:
    """
    GET with exponential backoff + jitter on transport errors and HTTP 5xx.
    Non-retryable: HTTP 4xx (except 429 could be added later).
    Returns (ok, detail).
    """
    last = "no attempt"
    for attempt in range(max_attempts):
        try:
            req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                code = int(getattr(resp, "status", resp.getcode()))
                body = resp.read(4096).decode("utf-8", errors="replace")
                if code >= 500:
                    last = f"HTTP {code}"
                    if on_attempt:
                        on_attempt(attempt, last)
                    if attempt + 1 < max_attempts:
                        sleep_backoff(
                            attempt,
                            base_sec=base_sec,
                            max_sec=max_backoff_sec,
                            jitter_ratio=jitter_ratio,
                        )
                    continue
                if code == 200:
                    return True, f"HTTP {code} len={len(body)}"
                return False, f"HTTP {code}"
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt + 1 < max_attempts:
                last = f"HTTP {e.code}"
                if on_attempt:
                    on_attempt(attempt, last)
                sleep_backoff(
                    attempt,
                    base_sec=base_sec,
                    max_sec=max_backoff_sec,
                    jitter_ratio=jitter_ratio,
                )
                continue
            return False, f"HTTP {e.code}: {e.reason}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = f"{type(e).__name__}: {e}"
            if on_attempt:
                on_attempt(attempt, last)
            if attempt + 1 >= max_attempts:
                break
            sleep_backoff(
                attempt,
                base_sec=base_sec,
                max_sec=max_backoff_sec,
                jitter_ratio=jitter_ratio,
            )
    return False, last


def retry_call(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    is_failure: Callable[[T], bool] | None = None,
    on_retry: Callable[[int], None] | None = None,
    base_sec: float = 0.15,
    max_backoff_sec: float = 10.0,
    jitter_ratio: float = 0.25,
) -> T:
    """Run *fn* until success or *max_attempts*. Treat exception as failure."""
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            out = fn()
            if is_failure is not None and is_failure(out):
                last_exc = None
                if attempt + 1 < max_attempts:
                    if on_retry:
                        on_retry(attempt)
                    sleep_backoff(
                        attempt,
                        base_sec=base_sec,
                        max_sec=max_backoff_sec,
                        jitter_ratio=jitter_ratio,
                    )
                continue
            return out
        except BaseException as e:
            last_exc = e
            if attempt + 1 >= max_attempts:
                raise
            if on_retry:
                on_retry(attempt)
            sleep_backoff(
                attempt,
                base_sec=base_sec,
                max_sec=max_backoff_sec,
                jitter_ratio=jitter_ratio,
            )
    if last_exc:
        raise last_exc
    raise RuntimeError("retry_call exhausted without result")
