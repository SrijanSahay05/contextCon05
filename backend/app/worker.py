"""Background worker: `python -m app.worker`. Claims jobs and runs their handlers to completion."""

import logging
import os
import socket
import time

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.enums import RunStatus
from app.services.jobs import queue
from app.services.jobs.registry import HANDLERS
from app.services.jobs.steps import CeilingReached, DeadlinePassed, StepRunner, set_run_status

logger = logging.getLogger("app.worker")
IDLE_SLEEP_SECONDS = 0.5


def run_once(db: Session, worker_id: str) -> bool:
    """Claim and run one job. Returns False when the queue was empty."""

    job = queue.claim(db, worker_id)
    if job is None:
        return False
    handler = HANDLERS.get(job.kind)
    if handler is None or job.run_id is None:
        queue.hold(db, job, f"no handler for {job.kind!r} or job has no run")
        return True
    set_run_status(db, job.run_id, RunStatus.running)
    try:
        handler(db, StepRunner(db, job.run_id), job.payload)
    except (CeilingReached, DeadlinePassed) as limit:
        db.rollback()
        queue.hold(db, job, str(limit))
        set_run_status(db, job.run_id, RunStatus.held, error=str(limit))
    except Exception as exc:
        db.rollback()
        logger.exception("job %s (%s) failed", job.id, job.kind)
        queue.fail(db, job, repr(exc))
        # a retry is still pending unless the job ran out of attempts
        status = RunStatus.held if job.status == RunStatus.held else RunStatus.queued
        set_run_status(db, job.run_id, status, error=repr(exc))
    else:
        queue.finish(db, job)
        set_run_status(db, job.run_id, RunStatus.done)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    with SessionLocal() as db:
        requeued = queue.requeue_stale(db)
        if requeued:
            logger.warning("requeued %d stale jobs", requeued)
    logger.info("worker %s started", worker_id)
    while True:
        with SessionLocal() as db:
            worked = run_once(db, worker_id)
        if not worked:
            time.sleep(IDLE_SLEEP_SECONDS)


if __name__ == "__main__":
    main()
