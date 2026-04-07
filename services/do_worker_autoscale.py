"""
Predictive DigitalOcean worker autoscale: combines **reactive** queue depth with **predictive**
headroom from feedback memory and calendar hints (GST filing window, Monday morning, local TZ).

1. **Learning** — ``adjusted_autoscale_pending_threshold()`` tightens the reactive threshold after
   failures / CPU stress (experience buffer).
2. **Prediction** — ``predictive_autoscale_threshold_adjustment()`` lowers that threshold when
   history shows this weekday/hour ran hot (``THIRAMAI_PREDICTIVE_MEMORY_RATIO`` vs learned
   threshold), or during configured calendar peaks.
3. **Economics** — ``economics_service.infra_scaling_budget_check`` runs **before** the droplet
   **create** (POST). Listing droplets (GET) only runs after the queue says scale may be needed.

Requires ``DIGITALOCEAN_TOKEN`` and ``THIRAMAI_DO_WORKER_SNAPSHOT_ID`` (numeric snapshot id).
Optional: ``THIRAMAI_DO_REGION``, ``THIRAMAI_DO_SIZE``, ``THIRAMAI_DO_SSH_KEY_IDS`` (comma ints),
``THIRAMAI_DO_WORKER_TAG`` (default ``thiramai-worker``).

Cooldown + max cap prevent runaway spend. Run from cron: ``python scripts/autoscale_digitalocean.py``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import httpx

from services.job_queue import count_pending_jobs

_log = logging.getLogger(__name__)

_DO_BASE = "https://api.digitalocean.com/v2"


def autoscale_enabled() -> bool:
    return (os.getenv("THIRAMAI_AUTOSCALE_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def _token() -> str:
    return (os.getenv("DIGITALOCEAN_TOKEN") or os.getenv("DO_TOKEN") or "").strip()


def _budget_organization_id() -> int:
    for key in ("THIRAMAI_AUTOSCALE_BUDGET_ORG_ID", "THIRAMAI_DEFAULT_ORG_ID"):
        raw = (os.getenv(key) or "").strip()
        if raw.isdigit():
            return int(raw)
    return 0


def _cooldown_ok() -> bool:
    path = Path(__file__).resolve().parents[1] / "var" / "autoscale_last_trigger.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    cool = int((os.getenv("THIRAMAI_AUTOSCALE_COOLDOWN_SEC") or "600").strip() or "600")
    if not path.is_file():
        return True
    try:
        last = float(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return True
    return (time.time() - last) >= cool


def _mark_cooldown() -> None:
    path = Path(__file__).resolve().parents[1] / "var" / "autoscale_last_trigger.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()), encoding="utf-8")


def count_droplets_by_tag(tag: str) -> int:
    tok = _token()
    if not tok:
        return 0
    try:
        r = httpx.get(
            f"{_DO_BASE}/droplets",
            params={"tag_name": tag},
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30.0,
        )
        r.raise_for_status()
        data = r.json()
        return len(data.get("droplets") or [])
    except Exception as exc:
        _log.warning("do_autoscale: list droplets failed: %s", exc)
        return -1


def create_worker_droplet(
    *,
    name_suffix: str,
    user_data: str | None = None,
    name_prefix: str | None = None,
    extra_tags: list[str] | None = None,
    snapshot_id: str | None = None,
) -> dict:
    tok = _token()
    snap = (snapshot_id or os.getenv("THIRAMAI_DO_WORKER_SNAPSHOT_ID") or "").strip()
    region = (os.getenv("THIRAMAI_DO_REGION") or "blr1").strip()
    size = (os.getenv("THIRAMAI_DO_SIZE") or "s-1vcpu-1gb").strip()
    tag = (os.getenv("THIRAMAI_DO_WORKER_TAG") or "thiramai-worker").strip()
    keys_raw = (os.getenv("THIRAMAI_DO_SSH_KEY_IDS") or "").strip()
    ssh_keys = [int(x.strip()) for x in keys_raw.split(",") if x.strip().isdigit()]
    if not tok or not snap.isdigit():
        return {"ok": False, "error": "DIGITALOCEAN_TOKEN and THIRAMAI_DO_WORKER_SNAPSHOT_ID required"}
    prefix = (name_prefix or "thiramai-worker").strip().rstrip("-") or "thiramai-worker"
    tags = [tag]
    if extra_tags:
        tags.extend([t.strip() for t in extra_tags if t and str(t).strip()])
    payload: dict = {
        "name": f"{prefix}-{name_suffix}"[:64],
        "region": region,
        "size": size,
        "image": int(snap),
        "tags": tags,
    }
    if ssh_keys:
        payload["ssh_keys"] = ssh_keys
    if user_data and user_data.strip():
        payload["user_data"] = user_data.strip()
    try:
        r = httpx.post(
            f"{_DO_BASE}/droplets",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json=payload,
            timeout=60.0,
        )
        if r.status_code not in (200, 201, 202):
            return {"ok": False, "error": f"DO {r.status_code}: {r.text[:800]}"}
        data = r.json().get("droplet") or {}
        return {"ok": True, "droplet_id": data.get("id"), "name": data.get("name")}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _build_learning_summary(out: dict) -> str:
    """Human-readable self-reflection for logs (and optional stdout when run as __main__)."""
    pred = out.get("predictive")
    if not isinstance(pred, dict):
        pred = {}
    reasons = pred.get("predictive_reasons") or []
    drop = int(pred.get("threshold_drop") or 0)
    tl = out.get("threshold_learning")
    tf = out.get("threshold_effective")
    mem_ratio = pred.get("memory_ratio")

    hint_parts: list[str] = []
    if "monday_morning" in reasons:
        hint_parts.append("past Monday peaks")
    if "memory_peak_hour" in reasons:
        mr = mem_ratio if mem_ratio is not None else 0.62
        hint_parts.append(f"memory for this weekday/hour (pending ≥ {float(mr) * 100:.0f}% of learned threshold)")
    if "gst_filing_window" in reasons:
        hint_parts.append("GST filing window")

    if drop > 0 and tl is not None and tf is not None:
        basis = ", ".join(hint_parts) if hint_parts else "calendar/memory signals"
        seg = f"Based on {basis}, I lowered the threshold by {drop} (from {tl} to {tf})."
    elif drop > 0:
        seg = f"I lowered the threshold by {drop}."
    else:
        seg = "No predictive threshold reduction this run."

    action = out.get("action")
    if action == "noop_operational_budget":
        tail = "Scaling was not triggered — operational budget cap exceeded."
    elif action == "noop_budget_check_error":
        tail = "Scaling was not triggered — operational budget check failed (see budget_check)."
    elif action == "scaled_up":
        tail = "Scaling was triggered within budget."
    elif action == "create_failed":
        tail = "Scaling was attempted but DigitalOcean provisioning failed."
    elif action in ("noop_queue_ok", "noop_at_cap", "noop_cooldown", "error_list_droplets"):
        tail = "Scaling was not triggered (queue depth, worker cap, cooldown, or droplet list error)."
    elif out.get("skipped"):
        tail = "Autoscale skipped (disabled)."
    else:
        tail = "Scaling was not triggered."

    return f"Learning Summary: {seg} {tail}"


def run_autoscale_once() -> dict:
    """
    Scale when ``pending_jobs`` meets the **predictive** threshold (memory + calendar + learning).

    ``infra_scaling_budget_check`` runs immediately before ``create_worker_droplet`` (POST).
    Droplet **list** (GET) runs only after queue depth says provisioning may be needed.
    """
    out: dict = {}
    try:
        if not autoscale_enabled():
            out = {
                "ok": True,
                "skipped": True,
                "reason": "THIRAMAI_AUTOSCALE_ENABLED off",
                "action": "skipped_disabled",
                "predictive": {},
            }
            return out
        if not _token():
            out = {"ok": False, "error": "DIGITALOCEAN_TOKEN not set", "action": "error_no_token", "predictive": {}}
            return out

        base_threshold = int((os.getenv("THIRAMAI_AUTOSCALE_PENDING_THRESHOLD") or "25").strip() or "25")
        try:
            from services.experience_buffer import (
                adjusted_autoscale_pending_threshold,
                predictive_autoscale_threshold_adjustment,
            )

            threshold_learning, threshold_adjustment = adjusted_autoscale_pending_threshold()
            pred = predictive_autoscale_threshold_adjustment(base_threshold=threshold_learning)
        except Exception as exc:
            _log.debug("experience_buffer autoscale adjust skipped: %s", exc)
            threshold_learning = base_threshold
            threshold_adjustment = {
                "base_threshold": base_threshold,
                "adjustments": [],
                "effective_threshold": base_threshold,
            }
            pred = {
                "predictive_active": False,
                "predictive_reasons": [],
                "effective_threshold": threshold_learning,
                "threshold_drop": 0,
                "memory_ratio": float((os.getenv("THIRAMAI_PREDICTIVE_MEMORY_RATIO") or "0.62").strip() or "0.62"),
                "memory_ratio_triggered": False,
            }

        threshold_final = int(pred.get("effective_threshold") or threshold_learning)
        max_nodes = int((os.getenv("THIRAMAI_AUTOSCALE_MAX_WORKERS") or "5").strip() or "5")
        tag = (os.getenv("THIRAMAI_DO_WORKER_TAG") or "thiramai-worker").strip()

        pending = count_pending_jobs()
        out = {
            "ok": True,
            "pending_jobs": pending,
            "threshold_base": base_threshold,
            "threshold_learning": threshold_learning,
            "threshold_adjustment": threshold_adjustment,
            "threshold_effective": threshold_final,
            "threshold": threshold_final,
            "predictive": pred,
            "droplets_tagged": None,
            "max_workers": max_nodes,
        }

        # No DigitalOcean calls until we might need to scale (pending vs predictive threshold).
        if pending < threshold_final:
            out["action"] = "noop_queue_ok"
            return out

        current = count_droplets_by_tag(tag)
        out["droplets_tagged"] = current
        if current < 0:
            out["ok"] = False
            out["error"] = "could not list droplets"
            out["action"] = "error_list_droplets"
            return out
        if current >= max_nodes:
            out["action"] = "noop_at_cap"
            return out
        if not _cooldown_ok():
            out["action"] = "noop_cooldown"
            return out

        try:
            from services.economics_service import infra_scaling_budget_check

            nodes_for_budget = max(0, current)
            bud = infra_scaling_budget_check(
                _budget_organization_id(),
                current_worker_nodes=nodes_for_budget,
            )
            out["budget_check"] = bud
            if not bud.get("allow_scale_up", True):
                out["action"] = "noop_operational_budget"
                return out
        except Exception as exc:
            _log.warning("infra_scaling_budget_check failed: %s", exc)
            out["budget_check"] = {"ok": False, "error": str(exc), "allow_scale_up": False}
            out["action"] = "noop_budget_check_error"
            return out

        suffix = str(int(time.time()))[-8:]
        created = create_worker_droplet(name_suffix=suffix)
        out["create"] = created
        if created.get("ok"):
            _mark_cooldown()
            out["action"] = "scaled_up"
            out["scale_mode"] = "predictive" if pred.get("predictive_active") else "reactive"
            _log.info("do_autoscale: created droplet %s mode=%s", created, out["scale_mode"])
        else:
            out["action"] = "create_failed"
        return out
    finally:
        if out:
            try:
                if not (os.getenv("THIRAMAI_AUTOSCALE_LEARNING_SUMMARY_DISABLED") or "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                    "on",
                ):
                    summary = _build_learning_summary(out)
                    out["learning_summary"] = summary
                    _log.info("%s", summary)
                try:
                    from services.thought_stream import append_thought

                    if out.get("learning_summary"):
                        append_thought(
                            str(out["learning_summary"])[:2000],
                            phase="autoscale",
                            agent="do_worker_autoscale",
                            meta={
                                "action": out.get("action"),
                                "scale_mode": out.get("scale_mode"),
                            },
                        )
                except Exception:
                    pass
                from services.experience_buffer import finalize_autoscale_run

                finalize_autoscale_run(out)
            except Exception as exc:
                _log.debug("finalize_autoscale_run skipped: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_autoscale_once()
    if result.get("learning_summary"):
        print(result["learning_summary"], flush=True)
    _log.info("autoscale_result %s", json.dumps(result, default=str))
