"""
DigitalOcean worker autoscale when the DB job queue is deep.

Requires ``THIRAMAI_DO_TOKEN``. When ``count_pending_jobs()`` exceeds
``THIRAMAI_AUTOSCALE_PENDING_THRESHOLD`` and tagged worker droplets are below
``THIRAMAI_DO_MAX_WORKER_DROPLETS``, creates a new droplet from ``THIRAMAI_DO_IMAGE``
(snapshot or slug) with tag ``THIRAMAI_DO_WORKER_TAG`` (default ``thiramai-worker``).

Cooldown: Redis key ``thiramai:autoscale:cooldown`` (TTL) if ``REDIS_URL`` is set; else
``var/autoscale_cooldown`` mtime.

Set ``THIRAMAI_DO_AUTOSCALE_DRY_RUN=1`` to log only (no API create).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from core.observability import log_structured
from services.job_queue import count_pending_jobs
from services.worker_heartbeat import redis_client


def _dry_run() -> bool:
    return (os.getenv("THIRAMAI_DO_AUTOSCALE_DRY_RUN") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _threshold() -> int:
    try:
        return max(1, int((os.getenv("THIRAMAI_AUTOSCALE_PENDING_THRESHOLD") or "25").strip()))
    except ValueError:
        return 25


def _max_workers() -> int:
    try:
        return max(1, int((os.getenv("THIRAMAI_DO_MAX_WORKER_DROPLETS") or "3").strip()))
    except ValueError:
        return 3


def _cooldown_sec() -> int:
    try:
        return max(60, int((os.getenv("THIRAMAI_DO_AUTOSCALE_COOLDOWN_SEC") or "600").strip()))
    except ValueError:
        return 600


def _worker_tag() -> str:
    return (os.getenv("THIRAMAI_DO_WORKER_TAG") or "thiramai-worker").strip() or "thiramai-worker"


def _cooldown_active() -> bool:
    ttl = _cooldown_sec()
    r = redis_client()
    if r is not None:
        try:
            if r.get("thiramai:autoscale:cooldown"):
                return True
        except Exception:
            pass
    path = Path(__file__).resolve().parents[1] / "var" / "autoscale_cooldown"
    try:
        if path.is_file():
            age = time.time() - path.stat().st_mtime
            return age < float(ttl)
    except OSError:
        pass
    return False


def _set_cooldown() -> None:
    ttl = _cooldown_sec()
    r = redis_client()
    if r is not None:
        try:
            r.setex("thiramai:autoscale:cooldown", ttl, str(time.time()))
            return
        except Exception:
            pass
    path = Path(__file__).resolve().parents[1] / "var" / "autoscale_cooldown"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def _do_headers() -> dict[str, str]:
    token = (os.getenv("THIRAMAI_DO_TOKEN") or os.getenv("DIGITALOCEAN_TOKEN") or "").strip()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _list_tagged_droplet_count(tag: str) -> tuple[int, str | None]:
    token = (os.getenv("THIRAMAI_DO_TOKEN") or os.getenv("DIGITALOCEAN_TOKEN") or "").strip()
    if not token:
        return 0, "missing_token"
    try:
        import httpx
    except ImportError:
        return 0, "no_httpx"
    url = "https://api.digitalocean.com/v2/droplets"
    params = {"tag_name": tag, "per_page": "200"}
    n = 0
    page_url: str | None = url
    with httpx.Client(timeout=45.0) as client:
        while page_url:
            r = client.get(page_url, headers=_do_headers(), params=params if page_url == url else None)
            if r.status_code != 200:
                return 0, f"list_http_{r.status_code}"
            data = r.json()
            droplets = data.get("droplets") or []
            n += len(droplets)
            links = (data.get("links") or {}).get("pages") or {}
            page_url = links.get("next")
            params = None
    return n, None


def _create_worker_droplet(tag: str) -> dict[str, Any]:
    region = (os.getenv("THIRAMAI_DO_REGION") or "nyc1").strip()
    size = (os.getenv("THIRAMAI_DO_SIZE") or "s-1vcpu-1gb").strip()
    image = (os.getenv("THIRAMAI_DO_IMAGE") or os.getenv("THIRAMAI_DO_SNAPSHOT_ID") or "").strip()
    if not image:
        return {"ok": False, "detail": "THIRAMAI_DO_IMAGE or THIRAMAI_DO_SNAPSHOT_ID required"}
    name = f"thiramai-worker-{uuid.uuid4().hex[:10]}"
    keys_raw = (os.getenv("THIRAMAI_DO_SSH_KEY_IDS") or "").strip()
    ssh_keys: list[int] = []
    if keys_raw:
        for part in keys_raw.split(","):
            part = part.strip()
            if part.isdigit():
                ssh_keys.append(int(part))
    user_data = (os.getenv("THIRAMAI_DO_USER_DATA") or "").strip() or _default_user_data()
    body: dict[str, Any] = {
        "name": name,
        "region": region,
        "size": size,
        "image": image,
        "tags": [tag],
        "user_data": user_data,
    }
    if ssh_keys:
        body["ssh_keys"] = ssh_keys
    if _dry_run():
        log_structured("do_autoscale.dry_run_create", name=name, region=region, size=size)
        return {"ok": True, "channel": "dry_run", "name": name}
    try:
        import httpx

        r = httpx.post(
            "https://api.digitalocean.com/v2/droplets",
            headers=_do_headers(),
            json=body,
            timeout=60.0,
        )
    except Exception as exc:
        return {"ok": False, "detail": type(exc).__name__}
    if r.status_code not in (200, 201, 202):
        return {"ok": False, "detail": f"create_http_{r.status_code}"}
    payload = r.json()
    did = (payload.get("droplet") or {}).get("id")
    log_structured("do_autoscale.droplet_created", droplet_id=did, name=name)
    return {"ok": True, "channel": "created", "droplet_id": did, "name": name}


def _default_user_data() -> str:
    """Minimal cloud-init hint; override with THIRAMAI_DO_USER_DATA on the server."""
    return """#cloud-config
runcmd:
  - echo "Provision THIRAMAI worker: set THIRAMAI_DO_USER_DATA to docker/cloud-init join script."
"""


def evaluate_and_maybe_scale() -> dict[str, Any]:
    token = (os.getenv("THIRAMAI_DO_TOKEN") or os.getenv("DIGITALOCEAN_TOKEN") or "").strip()
    if not token:
        return {"ok": True, "channel": "disabled", "detail": "no DO token"}
    enabled = (os.getenv("THIRAMAI_DO_AUTOSCALE") or "").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        return {"ok": True, "channel": "disabled", "detail": "THIRAMAI_DO_AUTOSCALE not enabled"}

    pending = count_pending_jobs()
    thr = _threshold()
    tag = _worker_tag()
    max_w = _max_workers()

    if pending < thr:
        return {
            "ok": True,
            "channel": "noop",
            "pending": pending,
            "threshold": thr,
        }

    if _cooldown_active():
        return {
            "ok": True,
            "channel": "cooldown",
            "pending": pending,
        }

    n_workers, err = _list_tagged_droplet_count(tag)
    if err:
        log_structured("do_autoscale.list_failed", error=err)
        return {"ok": False, "channel": "list_error", "detail": err, "pending": pending}

    if n_workers >= max_w:
        return {
            "ok": True,
            "channel": "at_cap",
            "pending": pending,
            "workers": n_workers,
            "max": max_w,
        }

    created = _create_worker_droplet(tag)
    if created.get("ok"):
        _set_cooldown()
    return {
        "ok": bool(created.get("ok")),
        "channel": created.get("channel", "create"),
        "pending": pending,
        "workers_before": n_workers,
        "result": created,
    }
