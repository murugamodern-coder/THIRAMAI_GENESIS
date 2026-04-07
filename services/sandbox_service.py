"""
Docker-backed sandbox: run pytest (and optional unified diff) in an isolated headless container.

Requires Docker Engine on the host and ``docker`` Python SDK. Disabled unless
``THIRAMAI_KERNEL_SANDBOX=1`` (or ``true``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import docker

SANDBOX_FLAG = "THIRAMAI_KERNEL_SANDBOX"
DEFAULT_IMAGE = "thiramai-sandbox:latest"
DEFAULT_MEM = "1g"


def sandbox_enabled() -> bool:
    return (os.getenv(SANDBOX_FLAG) or "").strip().lower() in ("1", "true", "yes", "on")


def sandbox_image() -> str:
    return (os.getenv("THIRAMAI_SANDBOX_IMAGE") or DEFAULT_IMAGE).strip() or DEFAULT_IMAGE


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def patches_dir() -> Path:
    p = repo_root() / "var" / "sandbox_patches"
    p.mkdir(parents=True, exist_ok=True)
    return p


def candidate_patch_path() -> Path:
    return patches_dir() / "candidate.patch"


def _docker_client():
    return docker.from_env()


def run_pytest_in_sandbox(
    *,
    pytest_targets: str = "tests/test_smoke.py tests/test_production_safety.py",
    timeout_sec: int = 600,
) -> tuple[int, str]:
    """
    Mount repo read-only at /workspace; ``var/sandbox_patches/candidate.patch`` at /patches (ro).

    Copies tree to /tmp/thiramai_ws inside the container, applies patch if non-empty, runs pytest.
    ``network_mode=none``. Returns (exit_code, combined stdout/stderr log).
    """
    if not sandbox_enabled():
        return 127, "sandbox disabled: set THIRAMAI_KERNEL_SANDBOX=1"

    root = repo_root()
    cpatch = candidate_patch_path()
    apply_block = ""
    if cpatch.is_file() and cpatch.stat().st_size > 0:
        apply_block = "patch -p1 < /patches/candidate.patch || { echo PATCH_FAILED; exit 2; }\n"

    inner_cmd = f"""
set -e
rm -rf /tmp/thiramai_ws
cp -a /workspace /tmp/thiramai_ws
cd /tmp/thiramai_ws
export PYTHONPATH=/tmp/thiramai_ws
{apply_block}exec python -m pytest {pytest_targets} --tb=short -q
""".strip()

    client = _docker_client()
    volumes: dict[str, dict[str, str]] = {
        str(root.resolve()): {"bind": "/workspace", "mode": "ro"},
        str(patches_dir().resolve()): {"bind": "/patches", "mode": "ro"},
    }

    try:
        out = client.containers.run(
            sandbox_image(),
            command=["/bin/bash", "-lc", inner_cmd],
            volumes=volumes,
            network_mode="none",
            mem_limit=os.getenv("THIRAMAI_SANDBOX_MEM", DEFAULT_MEM),
            remove=True,
            stdout=True,
            stderr=True,
            user="root",
            timeout=timeout_sec,
        )
        text = out.decode("utf-8", errors="replace") if isinstance(out, (bytes, bytearray)) else str(out)
        return 0, text
    except docker.errors.ContainerError as exc:
        logs = b""
        try:
            if exc.container is not None:
                logs = exc.container.logs() or b""
        except Exception:
            pass
        text = logs.decode("utf-8", errors="replace")
        code = int(getattr(exc, "exit_status", None) or 1)
        return code, text or str(exc)


def health() -> dict[str, Any]:
    """Best-effort Docker ping."""
    if not sandbox_enabled():
        return {"enabled": False, "docker": "skipped"}
    try:
        c = _docker_client()
        c.ping()
        return {"enabled": True, "docker": "ok", "image": sandbox_image()}
    except Exception as exc:
        return {"enabled": True, "docker": "error", "error": f"{type(exc).__name__}: {exc}"}
