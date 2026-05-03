#!/usr/bin/env python3
"""
Validate .env-style files for common container boot issues.

Does not load values into os.environ; parses KEY=VALUE lines only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load_env_lines(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    text = path.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def _validate_trusted_proxy_value(value: str) -> str | None:
    from core.settings import _parse_thiramai_trusted_proxy_ips

    try:
        _parse_thiramai_trusted_proxy_ips(value)
    except ValueError as e:
        return str(e)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate environment file for common issues")
    parser.add_argument("--file", default=".env.production", help="Path to env file")
    args = parser.parse_args()
    path = Path(args.file)
    print("=" * 70)
    print("ENVIRONMENT CONFIGURATION VALIDATION")
    print("=" * 70)
    print(f"\nValidating: {path.resolve()}\n")

    if not path.is_file():
        print(f"File not found: {path}")
        raise SystemExit(1)

    env = _load_env_lines(path)
    issues: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []

    required = ("DATABASE_URL", "SECRET_KEY", "JWT_SECRET_KEY", "THIRAMAI_CORS_ORIGINS")
    for key in required:
        val = env.get(key, "").strip()
        if not val:
            issues.append((key, "Required field missing or empty"))
        elif "CHANGE_ME" in val or val.upper().startswith("CHANGE_"):
            warnings.append((key, "Placeholder value — replace before real production"))
        else:
            if key == "DATABASE_URL":
                msg_extra = ""
                if not re.match(r"^(postgresql|postgres|postgresql\+[\w]+)://", val, re.I):
                    if val.startswith("sqlite:"):
                        msg_extra = " (sqlite dev)"
                    else:
                        warnings.append((key, f"Unexpected URL prefix: {val[:48]}..."))
                else:
                    msg_extra = "; URL scheme OK"
                print(f"OK {key}: present{msg_extra}")
            else:
                print(f"OK {key}: present")

    for tp_key in ("THIRAMAI_TRUSTED_PROXY_IPS", "TRUSTED_PROXY_IPS"):
        if tp_key not in env:
            continue
        val = env[tp_key]
        err = _validate_trusted_proxy_value(val)
        if err:
            issues.append((tp_key, err))
        else:
            print(f"OK {tp_key}: valid (empty, JSON array, or comma-separated)")

    v = env.get("REDIS_URL", "").strip()
    if v:
        if not v.lower().startswith("redis://"):
            warnings.append(("REDIS_URL", f"Expected redis://... got: {v[:48]}..."))
        else:
            print("OK REDIS_URL: URL scheme")

    print("\n" + "=" * 70)
    print("VALIDATION RESULTS")
    print("=" * 70)
    if issues:
        print("\nCRITICAL (fix before boot):")
        for k, msg in issues:
            print(f"  {k}: {msg}")
    if warnings:
        print("\nWARNINGS:")
        for k, msg in warnings:
            print(f"  {k}: {msg}")
    if not issues and not warnings:
        print("\nAll checks passed.")
    print("=" * 70)

    if issues:
        print(
            "\nTrusted proxy fix:\n"
            "  THIRAMAI_TRUSTED_PROXY_IPS=[]\n"
            "  # or comma-separated: 10.0.0.0/8,172.16.0.0/12\n"
            "  # or JSON: [\"127.0.0.1\"]"
        )
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
