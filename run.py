"""
THIRAMAI Genesis — root launcher with repository on ``sys.path``.

Use when imports fail because the working directory is not the project root, or when tooling
does not set ``PYTHONPATH``. Prefer: ``python run.py`` from the repo root. On Windows you can double-click ``DevServer.cmd`` (same as ``run.py``, reload on).

Equivalent to: ``uvicorn main:app --host 0.0.0.0 --port 8000`` with ``PYTHONPATH`` including
this directory. See also ``Start-Jarvis.ps1`` on Windows.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_root_str = str(ROOT)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)
_prev = os.environ.get("PYTHONPATH", "").strip()
os.environ["PYTHONPATH"] = _root_str + (os.pathsep + _prev if _prev else "")

if __name__ == "__main__":
    import uvicorn

    _host = (os.getenv("THIRAMAI_HOST") or "0.0.0.0").strip() or "0.0.0.0"
    _port = int((os.getenv("THIRAMAI_PORT") or "8000").strip() or "8000")
    _reload = (os.getenv("THIRAMAI_UVICORN_RELOAD") or "").strip().lower() in ("1", "true", "yes", "on")
    uvicorn.run("main:app", host=_host, port=_port, reload=_reload)
