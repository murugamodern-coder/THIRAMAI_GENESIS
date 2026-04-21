"""
Pre-flight and optional HTTP health validation for THIRAMAI startup.

Designed to be lightweight: short timeouts, no heavy imports of the FastAPI app
until ``run_system`` decides it is safe to bind.
"""

from __future__ import annotations

import dataclasses
import os
import re
import socket
import time
from pathlib import Path
from typing import Iterable


def log_line(tag: str, message: str = "") -> None:
    """Structured console line for operators (also use logging where app is loaded)."""
    if message:
        print(f"[{tag}] {message}", flush=True)
    else:
        print(f"[{tag}]", flush=True)


@dataclasses.dataclass
class CheckItem:
    name: str
    ok: bool
    detail: str = ""


@dataclasses.dataclass
class StartupReport:
    ok: bool
    items: list[CheckItem]
    degraded_recommended: bool

    def failed_names(self) -> list[str]:
        return [i.name for i in self.items if not i.ok]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def command_center_dir(root: Path | None = None) -> Path:
    base = root or _repo_root()
    return base / "static" / "command_center"


def check_required_env(required: Iterable[str]) -> CheckItem:
    missing = [k for k in required if not (k in os.environ and str(os.environ.get(k, "")).strip())]
    if missing:
        return CheckItem(
            name="env_required",
            ok=False,
            detail=f"missing or empty: {', '.join(missing)}",
        )
    return CheckItem(name="env_required", ok=True, detail="required keys present")


def check_command_center_files(root: Path | None = None) -> CheckItem:
    root = root or _repo_root()
    idx = command_center_dir(root) / "index.html"
    if not idx.is_file():
        return CheckItem(
            name="command_center_index",
            ok=False,
            detail=f"missing {idx}",
        )
    return CheckItem(name="command_center_index", ok=True, detail=str(idx))


_CC_ENTRY = re.compile(r"^cc-app-[A-Za-z0-9_.-]+\.js$")
_SRC = re.compile(r'src="([^"]+)"')
_HREF = re.compile(r'href="([^"]+)"')


def check_bundle_integrity(root: Path | None = None) -> CheckItem:
    """
    Ensures exactly one cc-app-*.js exists and index.html references it.
    Optionally verifies referenced sibling assets exist (same directory).
    """
    root = root or _repo_root()
    out = command_center_dir(root)
    if not out.is_dir():
        return CheckItem(name="bundle_integrity", ok=False, detail=f"missing directory {out}")

    try:
        names = list(out.iterdir())
    except OSError as e:
        return CheckItem(name="bundle_integrity", ok=False, detail=str(e))

    files = {p.name: p for p in names if p.is_file()}
    entry = [n for n in files if _CC_ENTRY.match(n)]
    if len(entry) != 1:
        return CheckItem(
            name="bundle_integrity",
            ok=False,
            detail=f"expected one cc-app-*.js, found {len(entry)}: {entry!r}",
        )
    entry_name = entry[0]
    html_path = out / "index.html"
    if not html_path.is_file():
        return CheckItem(name="bundle_integrity", ok=False, detail="index.html missing")

    try:
        text = html_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return CheckItem(name="bundle_integrity", ok=False, detail=f"read index: {e}")

    if entry_name not in text:
        return CheckItem(
            name="bundle_integrity",
            ok=False,
            detail=f"index.html does not reference {entry_name}",
        )

    missing_chunks: list[str] = []
    for pattern in (_SRC, _HREF):
        for m in pattern.finditer(text):
            ref = m.group(1).strip()
            if not ref or ref.startswith("http") or ref.startswith("//") or ref.startswith("data:"):
                continue
            # Vite emits relative module paths like ./cc-vendor-xxx.js or cc-app-xxx.js
            name = ref.split("/")[-1].split("?")[0]
            if not name or name == entry_name:
                continue
            if name.endswith(".js") or name.endswith(".css"):
                if name not in files:
                    missing_chunks.append(name)

    if missing_chunks:
        return CheckItem(
            name="bundle_integrity",
            ok=False,
            detail=f"missing referenced assets: {missing_chunks[:12]}"
            + (" …" if len(missing_chunks) > 12 else ""),
        )

    return CheckItem(name="bundle_integrity", ok=True, detail=f"entry={entry_name}")


def _parse_port(raw: str | None, default: int = 8000) -> int:
    if not raw or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def tcp_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def fetch_with_retries(
    url: str,
    *,
    retries: int = 3,
    timeout_sec: float = 3.0,
    backoff_sec: float = 0.4,
    circuit_base: str | None = None,
) -> tuple[bool, str]:
    """
    GET URL with exponential backoff + jitter (via stability layer) and optional circuit breaker.

    *circuit_base* — if set (e.g. ``http://127.0.0.1:8000``), failures open the breaker after
    consecutive failures cluster-wide for that base.
    """
    from core.stability.circuit_breaker import circuit_key_for_url, get_circuit_breaker
    from core.stability.retry import http_get_with_stability

    _ = backoff_sec  # retained for API compatibility; backoff is policy-driven in http_get_with_stability
    cb = get_circuit_breaker(circuit_key_for_url(circuit_base)) if circuit_base else None
    if cb and not cb.allow_request():
        return False, "circuit open (cooldown - API calls paused)"

    ok, detail = http_get_with_stability(
        url,
        timeout_sec=timeout_sec,
        max_attempts=max(1, retries),
        base_sec=float(os.environ.get("THIRAMAI_STABILITY_RETRY_BASE_SEC", "0.15") or "0.15"),
        max_backoff_sec=float(os.environ.get("THIRAMAI_STABILITY_RETRY_MAX_SEC", "8") or "8"),
        jitter_ratio=float(os.environ.get("THIRAMAI_STABILITY_RETRY_JITTER", "0.25") or "0.25"),
    )
    if cb:
        if ok:
            cb.record_success()
        else:
            cb.record_failure()
    return ok, detail


def check_api_health(
    base_url: str,
    *,
    retries: int = 3,
    timeout_sec: float = 3.0,
) -> CheckItem:
    base = base_url.rstrip("/")
    ok_live, d_live = fetch_with_retries(
        f"{base}/health/live",
        retries=retries,
        timeout_sec=timeout_sec,
        circuit_base=base,
    )
    ok_ready, d_ready = fetch_with_retries(
        f"{base}/health/ready",
        retries=retries,
        timeout_sec=timeout_sec,
        circuit_base=base,
    )
    if ok_live and ok_ready:
        return CheckItem(name="api_health", ok=True, detail=f"live: {d_live}; ready: {d_ready}")
    parts = []
    if not ok_live:
        parts.append(f"/health/live failed: {d_live}")
    if not ok_ready:
        parts.append(f"/health/ready failed: {d_ready}")
    return CheckItem(name="api_health", ok=False, detail="; ".join(parts))


def run_startup_checks(
    *,
    root: Path | None = None,
    probe_api_base: str | None = None,
    required_env: list[str] | None = None,
) -> StartupReport:
    """
    Run filesystem + env checks; optionally probe an already-running API (HTTP).

    * ``probe_api_base`` — e.g. ``http://127.0.0.1:8000`` (no trailing slash). If set,
      requires ``/health/live`` and ``/health/ready`` to succeed (with retries).
    * ``required_env`` — env var names that must be non-empty (default: none).
    """
    log_line("STARTUP CHECK", "running pre-bind validation")
    root = root or _repo_root()
    items: list[CheckItem] = []

    req = required_env if required_env is not None else []
    if req:
        items.append(check_required_env(req))
    else:
        items.append(CheckItem(name="env_required", ok=True, detail="no required keys configured"))

    items.append(check_command_center_files(root))
    items.append(check_bundle_integrity(root))

    degraded = any(not i.ok for i in items)

    if probe_api_base:
        items.append(
            check_api_health(
                probe_api_base,
                retries=int(os.environ.get("THIRAMAI_STARTUP_HEALTH_RETRIES", "3") or "3"),
                timeout_sec=float(os.environ.get("THIRAMAI_STARTUP_HEALTH_TIMEOUT_SEC", "3") or "3"),
            )
        )
        degraded = degraded or (not items[-1].ok)

    ok = all(i.ok for i in items)
    for it in items:
        status = "OK" if it.ok else "FAIL"
        log_line("STARTUP CHECK", f"{it.name}: {status} - {it.detail}")
    return StartupReport(ok=ok, items=items, degraded_recommended=degraded)


def schedule_post_bind_self_probe() -> None:
    """
    Fire-and-forget: after bind, verify ``/health/live`` from loopback (non-blocking for event loop).

    Called from FastAPI startup; uses a daemon thread with short timeouts.
    """
    import logging
    import threading

    logger = logging.getLogger("thiramai.startup")

    def _job() -> None:
        import os

        time.sleep(float(os.environ.get("THIRAMAI_STARTUP_POST_PROBE_DELAY_SEC", "0.8") or "0.8"))
        port = _parse_port(os.environ.get("THIRAMAI_PORT") or os.environ.get("PORT"))
        base = f"http://127.0.0.1:{port}"
        ok_live, d_live = fetch_with_retries(
            f"{base}/health/live",
            retries=3,
            timeout_sec=2.0,
            circuit_base=base,
        )
        if ok_live:
            log_line("HEALTH OK", f"post-bind live probe {d_live}")
            logger.info("[HEALTH OK] post-bind /health/live %s", d_live)
        else:
            log_line("HEALTH WARN", f"post-bind live probe failed: {d_live}")
            logger.warning("[HEALTH WARN] post-bind /health/live %s", d_live)

    threading.Thread(target=_job, name="thiramai-startup-probe", daemon=True).start()
