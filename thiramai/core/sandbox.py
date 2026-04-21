"""
Docker sandbox runner for THIRAMAI: execute allowlisted commands inside an isolated container
with the repository mounted at /workspace (no host shell, argv-only docker invocation).
"""

from __future__ import annotations

import json
import logging
import shlex
import subprocess
from pathlib import Path
from typing import Any

from thiramai.config import (
    THIRAMAI_SANDBOX_IMAGE,
    THIRAMAI_SANDBOX_MODE,
    THIRAMAI_SANDBOX_TIMEOUT_SEC,
)

logger = logging.getLogger("thiramai.sandbox")

# Repository root (parent of `thiramai/` package).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _validate_inner_argv(argv: list[str]) -> None:
    if not argv:
        raise ValueError("Sandbox inner argv cannot be empty.")
    binary = argv[0].lower()
    if binary not in {"python", "python3"}:
        raise ValueError(f"Sandbox only allows python as entrypoint, got: {argv[0]}")
    if len(argv) < 2:
        raise ValueError("Sandbox argv too short.")
    # Restrict to compile / inspect style subcommands (expand deliberately if needed).
    if argv[1] != "-m":
        raise ValueError("Sandbox only allows `python -m ...` invocations.")
    mod = argv[2].lower() if len(argv) > 2 else ""
    if mod not in {"py_compile", "compileall"}:
        raise ValueError(f"Sandbox disallowed -m target: {mod}")


def run_in_sandbox(command: str) -> dict[str, Any]:
    """
    Run a bounded command inside Docker.

    `command` is parsed with shlex; must resolve to `python -m py_compile <rel>` or
    `python -m compileall <rel>` with paths relative to repo root (no `..`, no absolute paths).
    """
    mode = THIRAMAI_SANDBOX_MODE
    if mode == "live":
        return {
            "status": "skipped",
            "returncode": 0,
            "output": "THIRAMAI_SANDBOX_MODE=live: Docker sandbox skipped by policy.",
            "error": "",
            "mode": "live",
        }

    parts = shlex.split(command, posix=True)
    _validate_inner_argv(parts)
    for token in parts[3:]:
        if ".." in token or token.startswith("/"):
            raise ValueError("Sandbox paths must be repo-relative without traversal.")

    docker_argv = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-v",
        f"{REPO_ROOT.resolve()}:/workspace:rw",
        "-w",
        "/workspace",
        THIRAMAI_SANDBOX_IMAGE,
        *parts,
    ]

    logger.info("Sandbox docker: %s", json.dumps(docker_argv))
    try:
        proc = subprocess.run(
            docker_argv,
            capture_output=True,
            text=True,
            timeout=THIRAMAI_SANDBOX_TIMEOUT_SEC,
            shell=False,
        )
        ok = proc.returncode == 0
        return {
            "status": "success" if ok else "error",
            "returncode": proc.returncode,
            "output": (proc.stdout or "").strip(),
            "error": (proc.stderr or "").strip(),
            "mode": "sandbox",
            "docker_argv": docker_argv,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "returncode": 124,
            "output": "",
            "error": f"Sandbox timed out after {THIRAMAI_SANDBOX_TIMEOUT_SEC}s",
            "mode": "sandbox",
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "returncode": -1,
            "output": "",
            "error": "docker CLI not found on PATH",
            "mode": "sandbox",
        }
    except Exception as exc:
        return {
            "status": "error",
            "returncode": -1,
            "output": "",
            "error": str(exc),
            "mode": "sandbox",
        }


def sandbox_py_compile(rel_path_under_repo: str) -> dict[str, Any]:
    """Convenience: `python -m py_compile <rel>` inside the sandbox container."""
    rel = rel_path_under_repo.replace("\\", "/").lstrip("/")
    if ".." in rel:
        raise ValueError("Invalid path")
    cmd = f"python -m py_compile {rel}"
    return run_in_sandbox(cmd)
