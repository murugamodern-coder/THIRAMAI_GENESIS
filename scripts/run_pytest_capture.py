"""
CI-friendly pytest runner (Windows-safe).

Pytest + Python 3.14 can hit ``ValueError: I/O operation on closed file`` when the process
stdout is redirected to a closed pipe. Discarding console while writing JUnit XML avoids that.

Usage (repo root)::

    .venv\\Scripts\\python.exe scripts\\run_pytest_capture.py

Or cmd::

    .venv\\Scripts\\python.exe -m pytest tests --junit-xml=junit_out.xml 1>NUL 2>NUL
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_XML = ROOT / "junit_out.xml"


def main() -> int:
    # NUL on Windows, /dev/null elsewhere
    sink = "NUL" if os.name == "nt" else "/dev/null"
    with open(sink, "w", encoding="utf-8", errors="replace") as devnull:
        p = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(ROOT / "tests"),
                "--junit-xml",
                str(OUT_XML),
            ],
            cwd=ROOT,
            stdout=devnull,
            stderr=devnull,
        )
    return int(p.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
