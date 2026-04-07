"""Orchestrator hook: log hot-reload signals at most once per new ``ts``."""

from __future__ import annotations

from core.kernel import hot_reload
from core.observability import log_structured

_last_logged_ts: float = 0.0


def maybe_log_pending_hot_reload(*, request_id: str) -> None:
    global _last_logged_ts
    pending = hot_reload.peek_pending()
    if not pending:
        return
    try:
        ts = float(pending.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0.0
    if ts <= _last_logged_ts:
        return
    _last_logged_ts = ts
    log_structured(
        "orchestrator.kernel_hot_reload_signal",
        request_id=request_id,
        patch_relative_path=pending.get("patch_relative_path"),
        pytest_exit_code=pending.get("pytest_exit_code"),
        ts=ts,
        hint="Supervised restart recommended to apply patch (Gunicorn multi-worker).",
    )
