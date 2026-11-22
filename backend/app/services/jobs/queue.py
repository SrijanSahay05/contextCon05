"""Postgres job queue: idempotent enqueue, SKIP LOCKED claims, backoff, crash recovery."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import RunKind, RunStatus
from app.models.runs import Job, Run

STALE_LOCK = timedelta(minutes=10)
BACKOFF_BASE_SECONDS = 5


def create_run(db: Session, kind: RunKind, subject: dict[str, Any]) -> Run:
    settings = get_settings()
    run = Run(
        kind=kind,
        subject=subject,
        credit_ceiling=settings.run_credit_ceiling,
        deadline=datetime.now(timezone.utc) + timedelta(minutes=settings.run_deadline_minutes),
    )
    db.add(run)
    db.flush()
    return run


def enqueue(
    db: Session,
    kind: str,
    payload: dict[str, Any],
    idempotency_key: str,
    run_id: uuid.UUID | None = None,
) -> Job:
    """Insert a job once; a repeated key returns the existing job instead of a duplicate."""

    db.execute(
        insert(Job)
        .values(kind=kind, payload=payload, idempotency_key=idempotency_key, run_id=run_id)
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    job = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    assert job is not None
    return job


def claim(db: Session, worker_id: str) -> Job | None:
    row = db.execute(
        text(
            """
            UPDATE job SET status = 'running', locked_at = now(), locked_by = :worker,
                           attempts = attempts + 1
            WHERE id = (
                SELECT id FROM job
                WHERE status = 'queued' AND run_after <= now()
                ORDER BY id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id
            """
        ),
        {"worker": worker_id},
    ).first()
    db.commit()
    return db.get(Job, row.id) if row else None


def finish(db: Session, job: Job) -> None:
    job.status = RunStatus.done
    job.locked_at = None
    db.commit()


def fail(db: Session, job: Job, error: str) -> None:
    """Retry with exponential backoff; after max attempts hold it for a person, never drop it."""

    job.last_error = error[:2000]
    job.locked_at = None
    if job.attempts >= job.max_attempts:
        job.status = RunStatus.held
    else:
        job.status = RunStatus.queued
        delay = BACKOFF_BASE_SECONDS * 2**job.attempts
        job.run_after = datetime.now(timezone.utc) + timedelta(seconds=delay)
    db.commit()


def hold(db: Session, job: Job, reason: str) -> None:
    job.status = RunStatus.held
    job.last_error = reason
    job.locked_at = None
    db.commit()


def requeue_stale(db: Session) -> int:
    """Jobs locked by a worker that died go back to the queue (crash recovery on startup)."""

    result = db.execute(
        update(Job)
        .where(Job.status == RunStatus.running)
        .where(Job.locked_at < datetime.now(timezone.utc) - STALE_LOCK)
        .values(status=RunStatus.queued, locked_at=None, locked_by=None)
    )
    db.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]
