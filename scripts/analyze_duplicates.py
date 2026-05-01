"""Module duplication & consolidation analysis for the Thiramai codebase.

Scans the *actual* tree (not a hard-coded list) and reports:

1. ``services/`` module count grouped by leading-token prefix.
2. For every duplicate group, the reverse-import map: who depends on each
   module right now. **Critical for safe consolidation** — a module with
   live importers cannot be deleted without redirecting them first.
3. A recommended consolidation plan, with each candidate clearly marked
   ``SAFE``, ``RISKY``, or ``BLOCKED`` based on those reverse-imports.

Run::

    python scripts/analyze_duplicates.py             # human-readable report
    python scripts/analyze_duplicates.py --json      # machine-readable

The script is read-only — it never modifies, moves, or deletes a file.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


# Prefix → "single-source-of-truth target" hints. The analyser uses these
# only as suggestions; it never assumes any of these targets exist.
_TARGET_HINTS: dict[str, str] = {
    "decision": "services/policy_engine.py",
    "goal": "services/goal_engine.py",
    "autonomy": "services/autonomy_safety_layer.py",
    "autonomous": "services/autonomy_safety_layer.py",
    "jarvis": "services/jarvis_proactive_engine.py",
    "research": "services/research_engine_service.py",
    "execution": "services/execution_engine.py",
    "agent": "services/agent_identity_continuity_engine.py",
    "continuous": "services/continuous_brain_loop.py",
    "world": "services/world_model_engine.py",
    "stock": "services/stock_market_data_service.py",
    "self": "services/self_evolution_trigger.py",
    "personal": "services/personal_command_center_service.py",
    "business": "services/business_service.py",
}


# Prefixes we always skip when grouping (too generic / not consolidation candidates).
_SKIP_PREFIXES = {
    "test",
    "__init__",
}


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _public_symbols(path: Path) -> dict[str, list[str]]:
    """Return ``{"classes": [...], "functions": [...]}`` for a Python file.

    Best-effort: any AST parse failure yields empty lists rather than raising.
    """
    classes: list[str] = []
    functions: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return {"classes": classes, "functions": functions}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            functions.append(node.name)
    return {"classes": classes, "functions": functions}


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Module discovery
# ---------------------------------------------------------------------------


def _scan_services() -> list[Path]:
    services = REPO_ROOT / "services"
    if not services.is_dir():
        return []
    out: list[Path] = []
    for root, _dirs, files in os.walk(services):
        # Skip generated / vendored / dynamic directories.
        if any(part in {"dynamic", "__pycache__", "tmp"} for part in Path(root).parts):
            continue
        for filename in files:
            if not filename.endswith(".py"):
                continue
            if filename.startswith("__init__") or filename.startswith("test_"):
                continue
            out.append(Path(root) / filename)
    return sorted(out)


def _module_dotted_path(file_path: Path) -> str:
    """``services/foo/bar.py`` → ``services.foo.bar`` (relative to repo root)."""
    rel = file_path.resolve().relative_to(REPO_ROOT)
    parts = list(rel.with_suffix("").parts)
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Reverse-import map
# ---------------------------------------------------------------------------


def _scan_repo_python_files() -> list[Path]:
    out: list[Path] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        # Skip junk / vendored.
        skip = {".git", ".venv", "venv", "node_modules", "__pycache__", "backups"}
        dirs[:] = [d for d in dirs if d not in skip]
        for filename in files:
            if filename.endswith(".py"):
                out.append(Path(root) / filename)
    return out


# Regex fallbacks for files we cannot AST-parse (e.g. syntax errors, Py2).
# AST is the source of truth - these only run when ast.parse() fails.
_FROM_IMPORT_RE = re.compile(r"^\s*from\s+(services(?:\.[a-zA-Z0-9_]+)+)\s+import\b", re.MULTILINE)
_DIRECT_IMPORT_RE = re.compile(r"^\s*import\s+(services(?:\.[a-zA-Z0-9_]+)+)\b", re.MULTILINE)
# ``from services import a, b as c`` - each name could be a submodule.
_FROM_PACKAGE_RE = re.compile(
    r"^\s*from\s+(services(?:\.[a-zA-Z0-9_]+)*)\s+import\s+([^\n#]+)",
    re.MULTILINE,
)
_NAME_TOKEN_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b(?:\s+as\s+[a-zA-Z_][a-zA-Z0-9_]*)?")


def _extract_service_refs(text: str) -> set[str]:
    """Return every ``services.<...>`` dotted path referenced by an import.

    Tries AST first (handles every legal form including
    ``from services import a, b as c`` and parenthesised multi-line lists).
    Falls back to regex only if the file fails to parse.
    """
    refs: set[str] = set()
    try:
        tree = ast.parse(text)
    except Exception:
        # Regex fallback for unparseable files.
        for match in _FROM_IMPORT_RE.finditer(text):
            refs.add(match.group(1))
        for match in _DIRECT_IMPORT_RE.finditer(text):
            refs.add(match.group(1))
        for match in _FROM_PACKAGE_RE.finditer(text):
            base = match.group(1)
            for name_match in _NAME_TOKEN_RE.finditer(match.group(2)):
                token = name_match.group(1)
                if token in {"as", "import"}:
                    continue
                refs.add(f"{base}.{token}")
        return refs

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "services" or alias.name.startswith("services."):
                    refs.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            module = node.module
            if module != "services" and not module.startswith("services."):
                continue
            refs.add(module)
            # Each imported name might itself be a submodule (the only way to
            # tell ``from services import foo`` from ``from services import bar``
            # is to assume both could be real modules and let the lookup decide).
            for alias in node.names:
                if alias.name == "*":
                    continue
                refs.add(f"{module}.{alias.name}")
    return refs


def _build_reverse_imports(modules: list[Path]) -> dict[str, list[str]]:
    """Single-pass reverse-import index.

    Each repo file is parsed once with the AST; we then look up every
    ``services.<...>`` reference against the target set, giving
    O(files + total_imports) instead of O(modules x files).
    """
    target_set = {_module_dotted_path(p) for p in modules}
    target_to_rel = {
        _module_dotted_path(p): str(p.relative_to(REPO_ROOT)).replace("\\", "/")
        for p in modules
    }
    importers: dict[str, set[str]] = {dotted: set() for dotted in target_set}

    for src in _scan_repo_python_files():
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel_src = str(src.relative_to(REPO_ROOT)).replace("\\", "/")
        for dotted in _extract_service_refs(text):
            if dotted in target_set and rel_src != target_to_rel[dotted]:
                importers[dotted].add(rel_src)

    return {dotted: sorted(paths) for dotted, paths in importers.items()}


# ---------------------------------------------------------------------------
# Group by prefix
# ---------------------------------------------------------------------------


def _prefix_for(path: Path) -> str | None:
    name = path.stem
    if name in _SKIP_PREFIXES:
        return None
    prefix = name.split("_", 1)[0].lower()
    if prefix in _SKIP_PREFIXES:
        return None
    return prefix


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------


def _classify(reverse_count: int, line_count: int) -> str:
    if reverse_count == 0 and line_count < 200:
        return "SAFE"
    if reverse_count == 0:
        return "REVIEW"
    if reverse_count <= 2:
        return "RISKY"
    return "BLOCKED"


def build_plan() -> dict[str, Any]:
    modules = _scan_services()
    reverse = _build_reverse_imports(modules)

    # Group services modules by prefix.
    by_prefix: dict[str, list[Path]] = defaultdict(list)
    for path in modules:
        prefix = _prefix_for(path)
        if prefix is None:
            continue
        by_prefix[prefix].append(path)

    # Build per-group reports.
    groups: list[dict[str, Any]] = []
    for prefix, paths in sorted(by_prefix.items()):
        if len(paths) < 2:
            continue
        target_hint = _TARGET_HINTS.get(prefix)
        members: list[dict[str, Any]] = []
        for path in sorted(paths):
            dotted = _module_dotted_path(path)
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            symbols = _public_symbols(path)
            lines = _line_count(path)
            importers = reverse.get(dotted, [])
            classification = _classify(len(importers), lines)
            members.append(
                {
                    "path": rel,
                    "dotted": dotted,
                    "lines": lines,
                    "classes": symbols["classes"][:10],
                    "functions": symbols["functions"][:10],
                    "importers": sorted(set(importers)),
                    "importer_count": len(set(importers)),
                    "consolidation": classification,
                }
            )
        # Sort: BLOCKED first (those should keep their place), then SAFE
        # candidates last (those are the deletion candidates).
        order = {"BLOCKED": 0, "RISKY": 1, "REVIEW": 2, "SAFE": 3}
        members.sort(key=lambda m: order.get(m["consolidation"], 4))

        # Plan summary for this group.
        safe_to_remove = [m["path"] for m in members if m["consolidation"] == "SAFE"]
        keep_candidates = [m["path"] for m in members if m["consolidation"] == "BLOCKED"]
        groups.append(
            {
                "prefix": prefix,
                "module_count": len(members),
                "target_hint": target_hint,
                "members": members,
                "safe_to_remove_now": safe_to_remove,
                "blocked_keep": keep_candidates,
            }
        )

    total = len(modules)
    duplicate_count = sum(g["module_count"] for g in groups)
    safe_removable = sum(len(g["safe_to_remove_now"]) for g in groups)

    return {
        "repo_root": str(REPO_ROOT),
        "services_module_count": total,
        "groups_with_duplicates": len(groups),
        "modules_in_duplicate_groups": duplicate_count,
        "safe_removable_modules": safe_removable,
        "estimated_post_consolidation_count": total - safe_removable,
        "groups": groups,
    }


# ---------------------------------------------------------------------------
# Pretty printer
# ---------------------------------------------------------------------------


_LEGEND = {
    "SAFE": "no live importers; small file - candidate for removal",
    "REVIEW": "no live importers but >=200 lines - inspect before removal",
    "RISKY": "1-2 live importers - migrate them, then remove",
    "BLOCKED": ">2 live importers - keep or perform a tracked refactor",
}


def print_report(plan: dict[str, Any]) -> None:
    print("=" * 78)
    print("THIRAMAI MODULE CONSOLIDATION ANALYSIS")
    print("=" * 78)
    print(f"services/ modules scanned        : {plan['services_module_count']}")
    print(f"prefix groups with >=2 members    : {plan['groups_with_duplicates']}")
    print(f"modules in those groups           : {plan['modules_in_duplicate_groups']}")
    print(f"SAFE-removable modules (no imports): {plan['safe_removable_modules']}")
    print(f"estimated post-consolidation count : {plan['estimated_post_consolidation_count']}")
    print()
    print("Legend:")
    for k, v in _LEGEND.items():
        print(f"  {k:7s} : {v}")
    print()

    for group in plan["groups"]:
        print("-" * 78)
        target = group["target_hint"] or "(no canonical target hinted)"
        print(f"PREFIX '{group['prefix']}'   ({group['module_count']} modules)   target hint: {target}")
        print("-" * 78)
        for m in group["members"]:
            print(
                f"  [{m['consolidation']:7s}] {m['path']:60s} "
                f"L={m['lines']:>5d}  importers={m['importer_count']}"
            )
            if m["importers"]:
                for imp in m["importers"][:5]:
                    print(f"             -> {imp}")
                if len(m["importers"]) > 5:
                    print(f"             -> ... and {len(m['importers']) - 5} more")
        if group["safe_to_remove_now"]:
            print()
            print("  Safe to remove now (no live importers):")
            for p in group["safe_to_remove_now"]:
                print(f"    rm {p}")
        if group["blocked_keep"]:
            print()
            print("  Blocked (>2 importers - keep until callers are migrated):")
            for p in group["blocked_keep"]:
                print(f"    keep {p}")
        print()

    print("=" * 78)
    print("END")
    print("=" * 78)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a report")
    parser.add_argument("--out", help="write JSON to this path (implies --json)")
    args = parser.parse_args(argv)

    plan = build_plan()

    if args.out:
        Path(args.out).write_text(json.dumps(plan, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
        return 0
    if args.json:
        print(json.dumps(plan, indent=2))
        return 0
    print_report(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
