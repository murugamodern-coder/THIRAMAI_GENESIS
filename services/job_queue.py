"""
DB-backed background job queue for API ↔ worker process separation.

When ``THIRAMAI_JOB_QUEUE=db``, billing routes enqueue rows in ``background_jobs`` instead of
using FastAPI ``BackgroundTasks``. Run ``python -m workers.run_worker`` in a separate process.

Default ``THIRAMAI_JOB_QUEUE=inline`` keeps in-process ``BackgroundTasks`` (dev / single-node).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import BackgroundTasks
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import BackgroundJob
from core.observability import clear_log_context, log_event, new_request_id, set_log_context


def use_db_job_queue() -> bool:
    return (os.getenv("THIRAMAI_JOB_QUEUE") or "inline").strip().lower() == "db"


# Dead-letter / poison: stop retrying the same job_id after this many failed dispatch attempts
# (each claim increments ``attempts``; cap is the lesser of row ``max_attempts`` and this).
POISON_MAX_ATTEMPTS = 3


def enqueue_issue_invoice(
    *,
    organization_id: int,
    idempotency_key: str,
    invoice_payload: dict[str, Any],
    approval_id: str | None,
    user_feedback: str,
    resolved_by_user_id: int | None,
    correlation_id: str | None = None,
) -> int:
    """Insert a pending ``issue_invoice`` job; returns ``background_jobs.id``."""
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("DATABASE_URL is not configured (cannot enqueue jobs).")
    body: dict[str, Any] = {
        "handler": "issue_invoice",
        "invoice_payload": invoice_payload,
        "approval_id": approval_id,
        "user_feedback": user_feedback,
        "resolved_by_user_id": resolved_by_user_id,
    }
    with factory() as session:
        with session.begin():
            row = BackgroundJob(
                job_type="issue_invoice",
                organization_id=int(organization_id),
                idempotency_key=idempotency_key,
                payload=body,
                status="pending",
            )
            session.add(row)
            session.flush()
            jid = int(row.id)
    rid = new_request_id()
    log_event(
        rid,
        "job_queue.enqueued",
        ok=True,
        extra={
            "job_id": jid,
            "job_type": "issue_invoice",
            "idempotency_key": idempotency_key,
            "organization_id": organization_id,
            "correlation_id": (correlation_id or "").strip()[:128] or None,
        },
    )
    return jid


def enqueue_jarvis_proactive_scan(
    *,
    kind: Literal["morning", "realtime"],
    idempotency_key: str,
    correlation_id: str | None = None,
) -> int:
    """Enqueue global Jarvis proactive scan (``kind`` = morning all-users or realtime all-users)."""
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("DATABASE_URL is not configured (cannot enqueue jobs).")
    body: dict[str, Any] = {"handler": "jarvis_proactive", "kind": str(kind)}
    if correlation_id and str(correlation_id).strip():
        body["correlation_id"] = str(correlation_id).strip()[:128]
    with factory() as session:
        with session.begin():
            row = BackgroundJob(
                job_type="jarvis_proactive",
                organization_id=None,
                idempotency_key=idempotency_key[:512],
                payload=body,
                status="pending",
            )
            session.add(row)
            session.flush()
            jid = int(row.id)
    rid = new_request_id()
    log_event(
        rid,
        "job_queue.enqueued",
        ok=True,
        extra={"job_id": jid, "job_type": "jarvis_proactive", "kind": kind, "correlation_id": correlation_id},
    )
    return jid


def enqueue_brain_intent(
    *,
    organization_id: int,
    idempotency_key: str,
    intent_payload: dict[str, Any],
    approval_id: str | None,
    user_feedback: str,
    resolved_by_user_id: int | None,
    correlation_id: str | None = None,
) -> int:
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("DATABASE_URL is not configured (cannot enqueue jobs).")
    body: dict[str, Any] = {
        "handler": "brain_intent",
        "intent_payload": intent_payload,
        "approval_id": approval_id,
        "user_feedback": user_feedback,
        "resolved_by_user_id": resolved_by_user_id,
    }
    if correlation_id and str(correlation_id).strip():
        body["correlation_id"] = str(correlation_id).strip()[:128]
    with factory() as session:
        with session.begin():
            row = BackgroundJob(
                job_type="brain_intent",
                organization_id=int(organization_id),
                idempotency_key=idempotency_key,
                payload=body,
                status="pending",
            )
            session.add(row)
            session.flush()
            jid = int(row.id)
    rid = new_request_id()
    log_event(
        rid,
        "job_queue.enqueued",
        ok=True,
        extra={
            "job_id": jid,
            "job_type": "brain_intent",
            "idempotency_key": idempotency_key,
            "organization_id": organization_id,
            "correlation_id": (correlation_id or "").strip()[:128] or None,
        },
    )
    return jid


def schedule_invoice_job(
    background_tasks: BackgroundTasks,
    *,
    organization_id: int,
    idempotency_key: str,
    invoice_payload: dict[str, Any],
    approval_id: str | None,
    user_feedback: str,
    resolved_by_user_id: int | None,
    job_fn: Any,
    correlation_id: str | None = None,
) -> None:
    if use_db_job_queue():
        enqueue_issue_invoice(
            organization_id=organization_id,
            idempotency_key=idempotency_key,
            invoice_payload=invoice_payload,
            approval_id=approval_id,
            user_feedback=user_feedback,
            resolved_by_user_id=resolved_by_user_id,
            correlation_id=correlation_id,
        )
        return
    background_tasks.add_task(
        job_fn,
        invoice_payload,
        idempotency_key,
        approval_id=approval_id,
        user_feedback=user_feedback,
        resolved_by_user_id=resolved_by_user_id,
    )


def schedule_brain_intent_job(
    background_tasks: BackgroundTasks,
    *,
    organization_id: int,
    idempotency_key: str,
    intent_payload: dict[str, Any],
    approval_id: str | None,
    user_feedback: str,
    resolved_by_user_id: int | None,
    job_fn: Any,
    correlation_id: str | None = None,
) -> None:
    if use_db_job_queue():
        enqueue_brain_intent(
            organization_id=organization_id,
            idempotency_key=idempotency_key,
            intent_payload=intent_payload,
            approval_id=approval_id,
            user_feedback=user_feedback,
            resolved_by_user_id=resolved_by_user_id,
            correlation_id=correlation_id,
        )
        return
    background_tasks.add_task(
        job_fn,
        intent_payload,
        organization_id,
        idempotency_key,
        approval_id=approval_id,
        user_feedback=user_feedback,
        resolved_by_user_id=resolved_by_user_id,
    )


def _claim_next_job_sqlite(session: Session) -> BackgroundJob | None:
    row = session.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.status == "pending")
        .order_by(BackgroundJob.id.asc())
        .limit(1)
        .with_for_update()
    )
    if row is None:
        return None
    row.status = "processing"
    row.started_at = datetime.now(timezone.utc)
    row.attempts = int(row.attempts or 0) + 1
    session.flush()
    return row


def _claim_next_job_postgres(session: Session) -> BackgroundJob | None:
    raw = session.execute(
        text(
            """
            WITH c AS (
                SELECT id FROM background_jobs
                WHERE status = 'pending'
                ORDER BY id ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE background_jobs j
            SET status = 'processing',
                started_at = now(),
                attempts = j.attempts + 1
            FROM c
            WHERE j.id = c.id
            RETURNING j.id
            """
        )
    ).first()
    if raw is None:
        return None
    jid = int(raw[0])
    return session.get(BackgroundJob, jid)


def claim_next_job(session: Session) -> BackgroundJob | None:
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return _claim_next_job_postgres(session)
    return _claim_next_job_sqlite(session)


def count_pending_jobs() -> int:
    """Count rows with ``status == pending`` (for autoscale / monitoring)."""
    factory = get_session_factory()
    if factory is None:
        return 0
    with factory() as session:
        n = session.scalar(
            select(func.count()).select_from(BackgroundJob).where(BackgroundJob.status == "pending")
        )
        return int(n or 0)


def mark_job_done(session: Session, job_id: int) -> None:
    session.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == job_id)
        .values(status="completed", completed_at=datetime.now(timezone.utc), error_message=None)
    )


def mark_job_failed(session: Session, job: BackgroundJob, message: str) -> None:
    attempts = int(job.attempts or 0)
    max_a = int(job.max_attempts or 5)
    # Poison / dead-letter: never retry past min(max_attempts, POISON_MAX_ATTEMPTS)
    ceiling = min(max_a, POISON_MAX_ATTEMPTS)
    if attempts >= ceiling:
        status = "dead"
        completed_at = datetime.now(timezone.utc)
        started_at = job.started_at
    else:
        status = "pending"
        completed_at = None
        started_at = None
    session.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == job.id)
        .values(
            status=status,
            error_message=message[:8000],
            completed_at=completed_at,
            started_at=started_at,
        )
    )


@dataclass(frozen=True)
class _JobSnap:
    id: int
    job_type: str
    idempotency_key: str
    organization_id: int | None
    payload: dict[str, Any]


def dispatch_job_snap(snap: _JobSnap) -> None:
    from workers import jobs as worker_jobs

    p = snap.payload
    handler = (p.get("handler") or "").strip()
    if handler == "issue_invoice":
        worker_jobs.job_execute_approved_invoice(
            p["invoice_payload"],
            snap.idempotency_key,
            approval_id=p.get("approval_id"),
            user_feedback=str(p.get("user_feedback") or ""),
            resolved_by_user_id=p.get("resolved_by_user_id"),
        )
        return
    if handler == "brain_intent":
        oid = int(snap.organization_id or 0)
        worker_jobs.job_execute_brain_intent(
            p["intent_payload"],
            oid,
            snap.idempotency_key,
            approval_id=p.get("approval_id"),
            user_feedback=str(p.get("user_feedback") or ""),
            resolved_by_user_id=p.get("resolved_by_user_id"),
        )
        return
    if handler == "jarvis_proactive":
        worker_jobs.job_execute_jarvis_proactive(kind=str(p.get("kind") or "").strip().lower())
        return
    raise ValueError(f"unknown job handler: {handler!r}")


def process_one_job() -> bool:
    factory = get_session_factory()
    if factory is None:
        return False
    snap: _JobSnap | None = None
    with factory() as session:
        with session.begin():
            job = claim_next_job(session)
            if job is None:
                return False
            pl = job.payload
            if not isinstance(pl, dict):
                pl = json.loads(json.dumps(pl))
            snap = _JobSnap(
                id=int(job.id),
                job_type=job.job_type,
                idempotency_key=job.idempotency_key,
                organization_id=job.organization_id,
                payload=dict(pl),
            )
    assert snap is not None
    cid: str | None = None
    if isinstance(snap.payload, dict):
        raw_c = snap.payload.get("correlation_id")
        if isinstance(raw_c, str) and raw_c.strip():
            cid = raw_c.strip()[:128]
    if cid:
        set_log_context(trace_id=cid)
    try:
        try:
            dispatch_job_snap(snap)
        except Exception as exc:
            with factory() as session:
                with session.begin():
                    j2 = session.get(BackgroundJob, snap.id)
                    if j2 is not None:
                        mark_job_failed(session, j2, str(exc))
            rid = new_request_id()
            log_event(
                rid,
                "job_queue.job_failed",
                ok=False,
                error=str(exc),
                extra={"job_id": snap.id, "job_type": snap.job_type, "correlation_id": cid},
            )
            return True
        with factory() as session:
            with session.begin():
                mark_job_done(session, snap.id)
        rid = new_request_id()
        log_event(
            rid,
            "job_queue.job_completed",
            ok=True,
            extra={"job_id": snap.id, "job_type": snap.job_type, "correlation_id": cid},
        )
        return True
    finally:
        if cid:
            clear_log_context()
