"""Print Alembic revision / down_revision string lengths (max 32 for VARCHAR(32) DBs)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "alembic" / "versions"

REV_PATTERNS = [
    re.compile(r'^revision\s*=\s*["\']([^"\']+)["\']', re.M),
    re.compile(r'^revision:\s*str\s*=\s*["\']([^"\']+)["\']', re.M),
]
DOWN_PATTERNS = [
    re.compile(r'^down_revision\s*=\s*["\']([^"\']+)["\']', re.M),
    re.compile(r'^down_revision:\s*[^=]+=\s*["\']([^"\']+)["\']', re.M),
]


def main() -> int:
    revs: list[tuple[str, str]] = []
    downs: list[tuple[str, str]] = []
    for path in sorted(ROOT.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pat in REV_PATTERNS:
            for m in pat.finditer(text):
                revs.append((m.group(1), path.name))
        for pat in DOWN_PATTERNS:
            for m in pat.finditer(text):
                downs.append((m.group(1), path.name))
    long_rev = sorted({(r, f, len(r)) for r, f in revs if len(r) > 32}, key=lambda x: -x[2])
    long_down = sorted({(d, f, len(d)) for d, f in downs if len(d) > 32}, key=lambda x: -x[2])
    print("revision ids > 32 chars:", len(long_rev))
    for r, fn, L in long_rev:
        print(f"  {L:2d}  {r}  ({fn})")
    print("down_revision targets > 32 chars:", len(long_down))
    for d, fn, L in long_down:
        print(f"  {L:2d}  {d}  (from {fn})")
    if long_rev or long_down:
        print(
            "\nNote: DBs with alembic_version.version_num VARCHAR(32) need it widened "
            "(see migration 0028_habit_health_vitals) before recording long revision ids."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
