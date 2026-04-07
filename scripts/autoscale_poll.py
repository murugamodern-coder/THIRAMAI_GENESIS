"""
Poll job queue depth and optionally create DigitalOcean worker droplets.

Cron (every 5 min)::

    THIRAMAI_DO_AUTOSCALE=1 THIRAMAI_DO_TOKEN=... \\
      DATABASE_URL=... python scripts/autoscale_poll.py

Environment: see ``services/do_autoscale.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(dotenv_path=ROOT / ".env", override=True)

from services.do_autoscale import evaluate_and_maybe_scale  # noqa: E402


def main() -> None:
    out = evaluate_and_maybe_scale()
    print(out)


if __name__ == "__main__":
    main()
