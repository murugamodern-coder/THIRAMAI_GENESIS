"""Lightweight counters and error ring for /ai/internal/* observability."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

_lock = threading.Lock()
_failure_count = 0
_step_count = 0
_retry_count = 0
_jobs_completed = 0
_jobs_completed_ok = 0
_jobs_completed_fail = 0
_job_duration_ms_total = 0.0
_llm_tokens_est_total = 0
_llm_calls_ok = 0
_llm_calls_fail = 0
_llm_latency_ms_total = 0.0
_last_errors: deque[dict[str, Any]] = deque(maxlen=50)

_SAMPLE_CAP = 2000
_job_duration_samples: deque[float] = deque(maxlen=_SAMPLE_CAP)
_llm_latency_samples: deque[float] = deque(maxlen=_SAMPLE_CAP)
_queue_wait_samples: deque[float] = deque(maxlen=_SAMPLE_CAP)


def _percentile(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    idx = min(n - 1, max(0, int(round((q / 100.0) * (n - 1)))))
    return float(s[idx])


def advanced_latency_snapshot() -> dict[str, Any]:
    """Rolling p95/p99 over recent samples (phase 53)."""
    with _lock:
        jd = list(_job_duration_samples)
        lm = list(_llm_latency_samples)
        qw = list(_queue_wait_samples)
    return {
        "goal_job_duration_ms": {
            "p95": round(_percentile(jd, 95), 3),
            "p99": round(_percentile(jd, 99), 3),
            "samples": len(jd),
        },
        "llm_latency_ms": {
            "p95": round(_percentile(lm, 95), 3),
            "p99": round(_percentile(lm, 99), 3),
            "samples": len(lm),
        },
        "queue_wait_ms": {
            "p95": round(_percentile(qw, 95), 3),
            "p99": round(_percentile(qw, 99), 3),
            "samples": len(qw),
        },
    }


def record_step() -> None:
    global _step_count
    with _lock:
        _step_count += 1


def record_failure(message: str, *, extra: dict[str, Any] | None = None) -> None:
    global _failure_count
    with _lock:
        _failure_count += 1
        _last_errors.appendleft(
            {
                "ts": time.time(),
                "message": message[:2000],
                **(extra or {}),
            }
        )


def record_llm_tokens_est(n: int) -> None:
    global _llm_tokens_est_total
    with _lock:
        _llm_tokens_est_total += max(0, int(n))


def record_retry(*, extra: dict[str, Any] | None = None) -> None:
    global _retry_count
    with _lock:
        _retry_count += 1
        if extra:
            _last_errors.appendleft({"ts": time.time(), "message": "retry_event", **extra})


def record_job_completed(duration_ms: float, *, ok: bool) -> None:
    global _jobs_completed, _jobs_completed_ok, _jobs_completed_fail, _job_duration_ms_total
    dm = max(0.0, float(duration_ms))
    with _lock:
        _jobs_completed += 1
        _job_duration_ms_total += dm
        _job_duration_samples.append(dm)
        if ok:
            _jobs_completed_ok += 1
        else:
            _jobs_completed_fail += 1


def record_llm_call(*, latency_ms: float, ok: bool) -> None:
    global _llm_calls_ok, _llm_calls_fail, _llm_latency_ms_total
    lm = max(0.0, float(latency_ms))
    with _lock:
        _llm_latency_ms_total += lm
        _llm_latency_samples.append(lm)
        if ok:
            _llm_calls_ok += 1
        else:
            _llm_calls_fail += 1


def record_queue_wait_ms(wait_ms: float) -> None:
    with _lock:
        _queue_wait_samples.append(max(0.0, float(wait_ms)))


def snapshot_counters() -> dict[str, Any]:
    with _lock:
        avg_job_ms = (
            (_job_duration_ms_total / _jobs_completed) if _jobs_completed > 0 else 0.0
        )
        llm_total = _llm_calls_ok + _llm_calls_fail
        avg_llm_ms = (_llm_latency_ms_total / llm_total) if llm_total > 0 else 0.0
        llm_success_rate = (_llm_calls_ok / llm_total) if llm_total > 0 else 0.0
        job_success_rate = (_jobs_completed_ok / _jobs_completed) if _jobs_completed > 0 else 0.0
        return {
            "autonomous_steps_total": _step_count,
            "failures_recorded_total": _failure_count,
            "retries_recorded_total": _retry_count,
            "goal_jobs_completed_total": _jobs_completed,
            "goal_jobs_ok_total": _jobs_completed_ok,
            "goal_jobs_failed_total": _jobs_completed_fail,
            "goal_jobs_avg_duration_ms": round(avg_job_ms, 3),
            "goal_jobs_success_rate": round(job_success_rate, 6),
            "llm_calls_ok_total": _llm_calls_ok,
            "llm_calls_fail_total": _llm_calls_fail,
            "llm_avg_latency_ms": round(avg_llm_ms, 3),
            "llm_success_rate": round(llm_success_rate, 6),
            "llm_tokens_estimated_total": _llm_tokens_est_total,
            "last_errors_buffered": len(_last_errors),
        }


def last_errors(limit: int = 25) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit), 50))
    with _lock:
        return list(_last_errors)[:lim]


def reset_for_tests() -> None:
    global _failure_count, _step_count, _retry_count, _jobs_completed
    global _jobs_completed_ok, _jobs_completed_fail, _job_duration_ms_total
    global _llm_tokens_est_total, _llm_calls_ok, _llm_calls_fail, _llm_latency_ms_total
    with _lock:
        _failure_count = 0
        _step_count = 0
        _retry_count = 0
        _jobs_completed = 0
        _jobs_completed_ok = 0
        _jobs_completed_fail = 0
        _job_duration_ms_total = 0.0
        _llm_tokens_est_total = 0
        _llm_calls_ok = 0
        _llm_calls_fail = 0
        _llm_latency_ms_total = 0.0
        _job_duration_samples.clear()
        _llm_latency_samples.clear()
        _queue_wait_samples.clear()
        _last_errors.clear()


def prometheus_text() -> str:
    """Minimal Prometheus exposition (text/plain). Coexists with ``/metrics`` Instrumentator."""
    from thiramai.runtime import goal_jobs

    gj = goal_jobs.aggregate_metrics()
    with _lock:
        steps = _step_count
        fails = _failure_count
        retries = _retry_count
        jcomp = gj["jobs_completed"]
        jrun = gj["jobs_running"]
        avg = gj["avg_execution_ms"]
        tok = _llm_tokens_est_total
        lines = [
            "# HELP thiramai_llm_tokens_estimated_total Estimated LLM tokens consumed (prompt coarse estimate).",
            "# TYPE thiramai_llm_tokens_estimated_total counter",
            f"thiramai_llm_tokens_estimated_total {tok}",
            "# HELP thiramai_autonomous_steps_total Total autonomous task steps executed.",
            "# TYPE thiramai_autonomous_steps_total counter",
            f"thiramai_autonomous_steps_total {steps}",
            "# HELP thiramai_failures_total Total recorded failures.",
            "# TYPE thiramai_failures_total counter",
            f"thiramai_failures_total {fails}",
            "# HELP thiramai_retries_total Total retry events.",
            "# TYPE thiramai_retries_total counter",
            f"thiramai_retries_total {retries}",
            "# HELP thiramai_goal_jobs_completed_total Completed goal jobs.",
            "# TYPE thiramai_goal_jobs_completed_total counter",
            f"thiramai_goal_jobs_completed_total {jcomp}",
            "# HELP thiramai_goal_jobs_running Current running goal jobs.",
            "# TYPE thiramai_goal_jobs_running gauge",
            f"thiramai_goal_jobs_running {jrun}",
            "# HELP thiramai_goal_job_avg_duration_ms Rolling average job duration.",
            "# TYPE thiramai_goal_job_avg_duration_ms gauge",
            f"thiramai_goal_job_avg_duration_ms {avg}",
        ]
    return "\n".join(lines) + "\n"
