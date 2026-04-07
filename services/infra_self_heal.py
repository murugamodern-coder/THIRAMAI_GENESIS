"""
Self-healing worker tier: detect missing Redis heartbeats for expected roles, provision a
replacement DigitalOcean droplet from snapshot, optionally inject cloud-init ``user_data``
for restore/bootstrap (operator-supplied script).

Fully unattended restore requires you to bake backup/restore logic into
``THIRAMAI_DO_USER_DATA_FILE`` (cloud-init) or snapshot image.

Env:
  ``THIRAMAI_SELF_HEAL_ENABLED``
  ``THIRAMAI_HEALTH_EXPECT_WORKERS`` — comma roles (e.g. ``job_worker,alert_worker``)
  ``THIRAMAI_SELF_HEAL_COOLDOWN_SEC`` — default 900
  ``THIRAMAI_DO_USER_DATA_FILE`` — optional cloud-init text for new droplets
  ``THIRAMAI_DO_HEAL_SNAPSHOT_ID`` — optional override snapshot (else worker snapshot)
  ``THIRAMAI_DO_HEAL_TAG`` — default ``thiramai-heal``
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from core.observability import log_event, new_request_id
from core.sovereign_journal import record_background_action, record_cot_step
from services import channels_bridge
from services.do_worker_autoscale import create_worker_droplet
from services.worker_heartbeat import any_heartbeat_for_role, expected_worker_roles_from_env

_log = logging.getLogger(__name__)


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def self_heal_enabled() -> bool:
    return _truthy("THIRAMAI_SELF_HEAL_ENABLED")


def _heal_cooldown_ok() -> bool:
    path = Path(__file__).resolve().parents[1] / "var" / "self_heal_last_trigger.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    cool = int((os.getenv("THIRAMAI_SELF_HEAL_COOLDOWN_SEC") or "900").strip() or "900")
    if not path.is_file():
        return True
    try:
        last = float(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return True
    return (time.time() - last) >= cool


def _mark_heal_cooldown() -> None:
    path = Path(__file__).resolve().parents[1] / "var" / "self_heal_last_trigger.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()), encoding="utf-8")


def _read_user_data() -> str | None:
    fp = (os.getenv("THIRAMAI_DO_USER_DATA_FILE") or "").strip()
    if not fp:
        return None
    p = Path(fp)
    if not p.is_file():
        _log.warning("infra_self_heal: user_data file missing: %s", fp)
        return None
    try:
        return p.read_text(encoding="utf-8")[:16000]
    except OSError as exc:
        _log.warning("infra_self_heal: user_data read failed: %s", exc)
        return None


def run_self_heal_scan(*, organization_id: int | None = None) -> dict:
    """
    For each expected worker role with no live heartbeat, create one heal droplet (cooldown-gated).
    """
    rid = new_request_id()
    if not self_heal_enabled():
        return {"ok": True, "skipped": True, "reason": "THIRAMAI_SELF_HEAL_ENABLED off"}
    roles = expected_worker_roles_from_env()
    if not roles:
        return {"ok": True, "skipped": True, "reason": "THIRAMAI_HEALTH_EXPECT_WORKERS empty"}

    missing = [r for r in roles if not any_heartbeat_for_role(r)]
    out: dict = {"ok": True, "checked": roles, "missing": missing, "actions": []}
    if not missing:
        log_event(rid, "infra_self_heal.scan", ok=True, extra={"missing": 0})
        return out
    if not _heal_cooldown_ok():
        out["action"] = "noop_cooldown"
        log_event(rid, "infra_self_heal.scan", ok=True, extra={"missing": len(missing), "cooldown": True})
        return out

    snap = (os.getenv("THIRAMAI_DO_HEAL_SNAPSHOT_ID") or os.getenv("THIRAMAI_DO_WORKER_SNAPSHOT_ID") or "").strip()
    tag = (os.getenv("THIRAMAI_DO_HEAL_TAG") or "thiramai-heal").strip()
    user_data = _read_user_data()
    suffix = str(int(time.time()))[-8:]
    created = create_worker_droplet(
        name_suffix=f"heal-{suffix}",
        user_data=user_data,
        name_prefix="thiramai-heal",
        extra_tags=[tag],
        snapshot_id=snap if snap.isdigit() else None,
    )
    out["actions"].append(created)
    record_cot_step(
        agent="infra_self_heal",
        phase="provision",
        detail=str(created)[:2000],
        organization_id=organization_id,
        trace_id=rid,
    )
    record_background_action(
        category="infra_heal",
        summary=f"Missing heartbeats {missing}; droplet create {created.get('ok')}",
        organization_id=organization_id,
        meta={"missing_roles": missing, "create": created},
    )
    notify_oid = organization_id
    if notify_oid is None:
        for k in ("THIRAMAI_SELF_HEAL_NOTIFY_ORG_ID", "THIRAMAI_DEFAULT_ORG_ID"):
            raw = (os.getenv(k) or "").strip()
            if raw.isdigit():
                notify_oid = int(raw)
                break
    if notify_oid is not None and created.get("ok"):
        channels_bridge.push_high_priority_alerts(
            organization_id=int(notify_oid),
            title="Self-heal: new worker droplet provisioned",
            body=f"Missing roles: **{', '.join(missing)}**\n\n`{created}`",
        )
    if created.get("ok"):
        _mark_heal_cooldown()
    log_event(
        rid,
        "infra_self_heal.scan",
        ok=bool(created.get("ok")),
        extra={"missing": len(missing), "droplet": created.get("droplet_id")},
    )
    return out
