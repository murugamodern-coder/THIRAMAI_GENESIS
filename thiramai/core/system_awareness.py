"""
THIRAMAI system awareness: bounded read-only snapshot of layout, dependencies,
host health, and best-effort service discovery (Docker).
"""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from thiramai.integrations.system_metrics import get_system_status

THIRAMAI_PKG = Path(__file__).resolve().parent.parent
REPO_ROOT = THIRAMAI_PKG.parent

MAX_FILES_WALK = 600
MAX_DEPTH = 5
MAX_DEP_LINES = 120
MAX_SERVICE_ROWS = 40


def _scan_files() -> dict[str, Any]:
    errors: list[str] = []
    extensions: Counter[str] = Counter()
    top_dirs: list[str] = []
    sample_py: list[str] = []
    total = 0

    try:
        th_dirs = [p.name for p in THIRAMAI_PKG.iterdir() if p.is_dir()]
        top_dirs = sorted(th_dirs)[:30]
    except OSError as exc:
        errors.append(f"thiramai listing: {exc}")
        th_dirs = []

    def walk(base: Path, depth: int) -> None:
        nonlocal total
        if depth > MAX_DEPTH or total >= MAX_FILES_WALK:
            return
        try:
            entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            errors.append(f"walk {base}: {exc}")
            return
        for entry in entries:
            if total >= MAX_FILES_WALK:
                break
            if entry.name.startswith(".") and entry.name not in {".", ".."}:
                continue
            if entry.is_file():
                total += 1
                ext = entry.suffix.lower() or "(no_ext)"
                extensions[ext] += 1
                if ext == ".py" and len(sample_py) < 35:
                    try:
                        rel = str(entry.relative_to(REPO_ROOT)).replace("\\", "/")
                    except ValueError:
                        rel = str(entry)
                    sample_py.append(rel)
            elif entry.is_dir() and depth < MAX_DEPTH:
                if entry.name in {"__pycache__", ".git", "node_modules", ".venv", "venv"}:
                    continue
                walk(entry, depth + 1)

    walk(THIRAMAI_PKG, 0)

    return {
        "repo_root": str(REPO_ROOT),
        "thiramai_package": str(THIRAMAI_PKG),
        "file_count_sampled": total,
        "extensions_top": dict(extensions.most_common(15)),
        "thiramai_top_dirs": top_dirs,
        "sample_python_files": sample_py,
        "errors": errors,
    }


def _read_dependency_files() -> dict[str, Any]:
    out: dict[str, Any] = {"files": {}, "errors": []}
    candidates = [
        REPO_ROOT / "requirements-base.txt",
        REPO_ROOT / "requirements.txt",
        REPO_ROOT / "requirements-production.txt",
        REPO_ROOT / "pyproject.toml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            out["files"][path.name] = {
                "line_count": len(lines),
                "head": lines[:MAX_DEP_LINES],
            }
        except OSError as exc:
            out["errors"].append(f"{path.name}: {exc}")
    return out


def _scan_services() -> dict[str, Any]:
    services: list[dict[str, str]] = []
    errors: list[str] = []
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        if proc.returncode != 0:
            errors.append(proc.stderr.strip() or f"docker ps exit {proc.returncode}")
            return {"services": services, "errors": errors, "raw_stderr": proc.stderr.strip()}

        for line in proc.stdout.splitlines():
            if len(services) >= MAX_SERVICE_ROWS:
                break
            line = line.strip()
            if not line:
                continue
            if "\t" in line:
                name, status = line.split("\t", 1)
            else:
                name, status = line, ""
            services.append({"name": name.strip(), "status": status.strip()})
    except FileNotFoundError:
        errors.append("docker CLI not found on PATH")
    except subprocess.TimeoutExpired:
        errors.append("docker ps timed out")
    except Exception as exc:
        errors.append(str(exc))

    return {"services": services, "errors": errors}


def _health_and_risks(files_info: dict[str, Any], deps_info: dict[str, Any], svc_info: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    health = get_system_status()
    risks: list[str] = []

    free_ratio = float(health.get("disk_free_ratio") or 0.0)
    if free_ratio < 0.1:
        risks.append("critical_low_disk_space")
    elif free_ratio < 0.2:
        risks.append("low_disk_space")

    if files_info.get("file_count_sampled", 0) >= MAX_FILES_WALK:
        risks.append("large_tree_scan_truncated")

    if deps_info.get("errors"):
        risks.append("dependency_manifest_read_errors")

    if svc_info.get("errors"):
        risks.append("container_runtime_unavailable_or_degraded")

    return health, risks


def system_scan() -> dict[str, Any]:
    """
    Produce a structured snapshot: files, services, errors, risks.
    Safe: read-only tree walk, bounded size, no shell execution except fixed docker argv.
    """
    errors: list[str] = []
    files_block = _scan_files()
    errors.extend(files_block.pop("errors", []))

    deps_block = _read_dependency_files()
    errors.extend(deps_block.get("errors", []))

    services_block = _scan_services()
    errors.extend(services_block.get("errors", []))

    health, risks = _health_and_risks(files_block, deps_block, services_block)
    risks = list(dict.fromkeys(risks))

    return {
        "files": files_block,
        "dependencies": deps_block.get("files", {}),
        "dependency_errors": deps_block.get("errors", []),
        "services": services_block.get("services", []),
        "service_errors": services_block.get("errors", []),
        "health": health,
        "errors": errors,
        "risks": risks,
    }


def system_scan_compact() -> dict[str, Any]:
    """Smaller payload for LLM prompts (drops long dep bodies)."""
    full = system_scan()
    deps_compact = {}
    for name, meta in full.get("dependencies", {}).items():
        if isinstance(meta, dict):
            deps_compact[name] = {
                "line_count": meta.get("line_count"),
                "head_preview": (meta.get("head") or [])[:25],
            }
    return {
        "files": {
            "file_count_sampled": full["files"].get("file_count_sampled"),
            "extensions_top": full["files"].get("extensions_top"),
            "thiramai_top_dirs": full["files"].get("thiramai_top_dirs"),
            "sample_python_files": (full["files"].get("sample_python_files") or [])[:15],
        },
        "dependencies": deps_compact,
        "services": full.get("services", [])[:15],
        "health": full.get("health"),
        "errors": full.get("errors", [])[:20],
        "risks": full.get("risks", []),
    }
