"""Read side of background runs: status, steps, ledger, and the SSE event stream."""

import json
import time
import uuid
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.errors import ApiError, ErrorCode
from app.models.enums import RunStatus
from app.models.evidence import Ledger
from app.models.runs import Run, RunStep
from app.schemas.run import LedgerRowOut, RunEvent, RunOut, RunStepOut, StepEvent
from app.services.jobs.steps import credits_spent

TERMINAL = {RunStatus.done, RunStatus.failed, RunStatus.held}
POLL_SECONDS = 1.0
LEDGER_ROWS = 50


def _get(db: Session, run_id: uuid.UUID) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise ApiError(404, ErrorCode.not_found, "Run not found")
    return run


def _steps(db: Session, run_id: uuid.UUID) -> list[RunStep]:
    return list(
        db.scalars(select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.seq))
    )


def get_run(db: Session, run_id: uuid.UUID) -> RunOut:
    run = _get(db, run_id)
    ledger = db.scalars(
        select(Ledger)
        .where(Ledger.run_id == run_id)
        .order_by(Ledger.id.desc())
        .limit(LEDGER_ROWS)
    )
    return RunOut(
        id=run.id,
        kind=run.kind,
        status=run.status,
        subject=run.subject,
        credit_ceiling=float(run.credit_ceiling),
        credits_spent=credits_spent(db, run_id),
        deadline=run.deadline,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        hold_reason=run.hold_reason,
        steps=[
            RunStepOut(
                name=s.name,
                seq=s.seq,
                status=s.status,
                attempt=s.attempt,
                output=s.output if isinstance(s.output, dict) else None,
                started_at=s.started_at,
                finished_at=s.finished_at,
            )
            for s in _steps(db, run_id)
        ],
        ledger=[
            LedgerRowOut(
                id=row.id,
                provider=row.provider,
                endpoint=row.endpoint,
                units=float(row.units),
                unit_type=row.unit_type,
                cached=row.cached,
                source_id=row.source_id,
                created_at=row.created_at,
            )
            for row in ledger
        ],
    )


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def stream_events(run_id: uuid.UUID, poll_seconds: float = POLL_SECONDS) -> Iterator[str]:
    """Emit `step` and `run` events when something changes; `end` once the run stops.

    Uses its own short sessions: the request's session is gone once streaming starts.
    """

    with SessionLocal() as db:
        _get(db, run_id)  # 404 before the stream opens
    seen_steps: dict[str, str] = {}
    seen_run: tuple[str, float] | None = None
    while True:
        with SessionLocal() as db:
            run = _get(db, run_id)
            for step in _steps(db, run_id):
                if seen_steps.get(step.name) != step.status:
                    seen_steps[step.name] = step.status
                    payload = StepEvent(name=step.name, status=step.status, seq=step.seq)
                    yield _sse("step", payload.model_dump_json())
            state = (str(run.status), credits_spent(db, run_id))
            if state != seen_run:
                seen_run = state
                yield _sse("run", RunEvent(status=run.status, credits_spent=state[1])
                           .model_dump_json())
            if run.status in TERMINAL:
                yield _sse("end", json.dumps({}))
                return
        time.sleep(poll_seconds)
