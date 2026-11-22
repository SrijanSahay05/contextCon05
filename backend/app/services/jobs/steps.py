"""Resumable run steps and per-run budget checks.

Handlers are written as a sequence of `runner.step(name, fn)` calls. A finished
step's output is stored, so after a crash the handler re-runs from the top and
every completed step returns its saved output instead of calling out again.
"""

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import RunStatus, StepStatus, UnitType
from app.models.evidence import Ledger
from app.models.runs import Run, RunStep

T = TypeVar("T")


class CeilingReached(Exception):
    """The run spent its credit ceiling; it is held for a person to raise or stop."""


class DeadlinePassed(Exception):
    """The run went past its time limit; it is held, not silently failed."""


class StepRunner:
    def __init__(self, db: Session, run_id: uuid.UUID) -> None:
        self.db = db
        self.run_id = run_id

    def step(self, name: str, fn: Callable[[], T]) -> T:
        existing = self.db.get(RunStep, (self.run_id, name))
        if existing is not None and existing.status == StepStatus.done:
            return existing.output  # type: ignore[no-any-return]

        seq = self.db.scalar(
            select(func.count()).select_from(RunStep).where(RunStep.run_id == self.run_id)
        )
        if existing is None:
            existing = RunStep(
                run_id=self.run_id, name=name, seq=seq or 0, status=StepStatus.running
            )
            self.db.add(existing)
        else:
            existing.status = StepStatus.running
            existing.attempt += 1
        self.db.commit()

        try:
            output = fn()
        except Exception:
            self.db.rollback()
            existing.status = StepStatus.failed
            self.db.commit()
            raise
        existing.output = output
        existing.status = StepStatus.done
        existing.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        return output


def credits_spent(db: Session, run_id: uuid.UUID) -> float:
    total = db.scalar(
        select(func.coalesce(func.sum(Ledger.units), 0))
        .where(Ledger.run_id == run_id)
        .where(Ledger.unit_type == UnitType.credits)
    )
    return float(total or 0)


def ensure_budget(db: Session, run_id: uuid.UUID) -> None:
    """Call before every paid external call; raises instead of overspending."""

    run = db.get(Run, run_id)
    if run is None:
        return
    spent = credits_spent(db, run_id)
    run.credits_spent = spent
    if spent >= float(run.credit_ceiling):
        raise CeilingReached(f"spent {spent:.2f} of {float(run.credit_ceiling):.2f} credits")
    if datetime.now(timezone.utc) > run.deadline:
        raise DeadlinePassed(f"deadline {run.deadline.isoformat()} passed")


def set_run_status(
    db: Session, run_id: uuid.UUID, status: RunStatus, *, error: str | None = None
) -> None:
    run = db.get(Run, run_id)
    if run is None:
        return
    now = datetime.now(timezone.utc)
    run.status = status
    if status == RunStatus.running and run.started_at is None:
        run.started_at = now
    if status in (RunStatus.done, RunStatus.failed):
        run.finished_at = now
    if status == RunStatus.held:
        run.hold_reason = error
    elif error:
        run.error = error
    run.credits_spent = credits_spent(db, run_id)
    db.commit()
