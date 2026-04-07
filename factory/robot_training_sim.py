"""
THIRAMAI — Bushing-joint AI training simulation (Phase 9).

``run_joint_simulation()`` runs **1000** PE100-weighted trials, writes JSON including
``success_rate``, ``failure_point_newtons``, ``iteration_count``, and a **terminal log tail**.

**Path note:** A ``brain/`` *package* would shadow the project root ``brain.py`` (FastAPI).
Shim for imports: ``brain_training/robot_training_sim.py``.

    python factory/robot_training_sim.py
"""

from __future__ import annotations

import json
import random
import sys
from collections import deque
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RD_CORE = ROOT / "vault" / "rd_core"
TRAINING_STATE_PATH = RD_CORE / "robot_training_last.json"

DEFAULT_TRIALS = 1000


def _success_probability_from_pe100(mean_score: float) -> float:
    m = max(0.0, min(100.0, mean_score))
    return min(0.92, max(0.62, 0.505 + 0.485 * (m / 100.0)))


def run_joint_simulation(
    *,
    trials: int = DEFAULT_TRIALS,
    seed: int = 42,
    persist: bool = True,
) -> dict[str, Any]:
    """
    Simulate **bushing-joint** movements under PE100-derived stress margins.

    Returns a dict (and optionally writes ``vault/rd_core/robot_training_last.json``) with:
    ``success_rate`` (0–1), ``failure_point_newtons`` (mean load at simulated joint failure),
    ``iteration_count``, ``trial_log_tail``, plus legacy dashboard keys.
    """
    from factory.design_engine import evaluate_pe100_structural_chassis

    pe = evaluate_pe100_structural_chassis()
    mean_score = float(pe.get("mean_score") or 64.0)
    mrs_mpa = float(pe.get("mrs_nominal_mpa") or 10.0)
    p = _success_probability_from_pe100(mean_score)
    rng = random.Random(seed)

    successes = 0
    failure_newtons: list[float] = []
    log_tail: deque[str] = deque(maxlen=24)

    # Illustrative joint area → force scale from MRS (N). PE100 bushing coupon proxy.
    joint_area_mm2 = 42.0
    nominal_limit_n = max(120.0, mrs_mpa * joint_area_mm2 * 0.85)

    for i in range(1, max(1, trials) + 1):
        if rng.random() < p:
            successes += 1
            log_tail.append(f"[SIM] Trial {i}: Success — bushing-joint within PE100 envelope.")
        else:
            margin = 0.55 + 0.40 * (mean_score / 100.0)
            fail_n = round(nominal_limit_n * margin * rng.uniform(0.82, 1.08), 1)
            failure_newtons.append(fail_n)
            log_tail.append(
                f"[SIM] Trial {i}: Stress Failure — joint slip/crack model @ ~{fail_n} N (exceeds print margin)."
            )

    n = max(1, trials)
    success_rate = round(successes / n, 4)
    success_rate_pct = round(100.0 * success_rate, 1)
    fail_avg_n = (
        round(sum(failure_newtons) / len(failure_newtons), 2) if failure_newtons else 0.0
    )
    now = datetime.now(timezone.utc).isoformat()

    out: dict[str, Any] = {
        "sim_type": "bushing_joint_pe100",
        "iteration_count": n,
        "success_rate": success_rate,
        "failure_point_newtons": fail_avg_n,
        "successes": successes,
        "trials": n,
        "success_rate_pct": success_rate_pct,
        "trial_log_tail": list(log_tail),
        "per_trial_p_success_model": round(p, 4),
        "random_seed": seed,
        "material_grade": pe.get("material_grade", "PE100"),
        "mean_pe100_criterion_score": mean_score,
        "pe100_overall_band": pe.get("overall_band", ""),
        "nominal_joint_limit_n": round(nominal_limit_n, 2),
        "run_utc": now,
        "run_date": date.today().isoformat(),
        "disclaimer": "Simulation only — not empirical robot logs.",
        "sim_id": "bushing_joint_pe100_v2",
    }

    if persist:
        RD_CORE.mkdir(parents=True, exist_ok=True)
        TRAINING_STATE_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def run_joint_movement_training(
    *,
    trials: int = DEFAULT_TRIALS,
    seed: int = 42,
) -> dict[str, Any]:
    """Backward-compatible alias for dashboard / older callers."""
    return run_joint_simulation(trials=trials, seed=seed, persist=True)


def read_last_training_run() -> dict[str, Any] | None:
    if not TRAINING_STATE_PATH.is_file():
        return None
    try:
        raw = json.loads(TRAINING_STATE_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def format_training_summary_line() -> str:
    d = read_last_training_run()
    if not d:
        return "No training run on disk — execute `python factory/robot_training_sim.py`."
    sr = d.get("success_rate")
    if sr is None and d.get("success_rate_pct") is not None:
        sr = float(d["success_rate_pct"]) / 100.0
    return (
        f"Last **bushing-joint sim**: **success_rate={sr}** "
        f"({d.get('successes')}/{d.get('iteration_count') or d.get('trials')} iters), "
        f"**failure_point_newtons** (mean of failed trials) **{d.get('failure_point_newtons')}**, "
        f"run **{d.get('run_utc')}**."
    )


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    r = run_joint_simulation(trials=max(1, args.trials), seed=args.seed, persist=True)
    print("ROBOT_TRAINING_OK", TRAINING_STATE_PATH)
    print(
        f"success_rate={r['success_rate']} ({r['success_rate_pct']}%)  "
        f"failure_point_newtons={r['failure_point_newtons']}  iteration_count={r['iteration_count']}"
    )


if __name__ == "__main__":
    main()
