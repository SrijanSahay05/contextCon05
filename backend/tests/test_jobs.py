from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import Provider, RunKind, RunStatus, StepStatus, UnitType
from app.models.evidence import Ledger
from app.models.runs import Job, Run, RunStep
from app.services.jobs import queue
from app.services.jobs.registry import HANDLERS
from app.services.jobs.steps import StepRunner, ensure_budget
from app.worker import run_once


def _job(db: Session, kind: str, key: str) -> tuple[Run, Job]:
    run = queue.create_run(db, RunKind.search, {"test": key})
    job = queue.enqueue(db, kind, {}, key, run.id)
    db.commit()
    return run, job


def test_crash_after_first_step_resumes_without_repeating_it(db: Session) -> None:
    calls: list[str] = []

    def record(name: str) -> dict[str, str]:
        calls.append(name)
        return {"step": name}

    def handler(db: Session, runner: StepRunner, payload: dict[str, Any]) -> None:
        runner.step("first", lambda: record("first"))
        if "crashed" not in calls:
            calls.append("crashed")
            raise RuntimeError("simulated crash after step 1")
        runner.step("second", lambda: record("second"))

    HANDLERS["test_two_step"] = handler
    run, job = _job(db, "test_two_step", "resume-1")

    assert run_once(db, "w1")
    db.refresh(job)
    assert job.status == RunStatus.queued and job.attempts == 1

    job.run_after = datetime.now(timezone.utc)  # skip the backoff delay
    db.commit()
    assert run_once(db, "w1")

    finished = db.get(Job, job.id)
    finished_run = db.get(Run, run.id)
    assert finished and finished.status == RunStatus.done
    assert finished_run and finished_run.status == RunStatus.done
    assert calls == ["first", "crashed", "second"]  # step one ran exactly once
    steps = db.scalars(select(RunStep).where(RunStep.run_id == run.id)).all()
    assert {s.name: s.status for s in steps} == {
        "first": StepStatus.done,
        "second": StepStatus.done,
    }


def test_enqueue_is_idempotent(db: Session) -> None:
    run = queue.create_run(db, RunKind.search, {})
    first = queue.enqueue(db, "anything", {}, "same-key", run.id)
    second = queue.enqueue(db, "anything", {"other": True}, "same-key", run.id)
    db.commit()
    assert first.id == second.id
    assert len(db.scalars(select(Job)).all()) == 1


def test_job_is_held_after_max_attempts(db: Session) -> None:
    def always_fails(db: Session, runner: StepRunner, payload: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    HANDLERS["test_always_fails"] = always_fails
    run, job = _job(db, "test_always_fails", "fail-1")
    for _ in range(job.max_attempts):
        job.run_after = datetime.now(timezone.utc)
        db.commit()
        run_once(db, "w1")
        db.refresh(job)
    db.refresh(run)
    assert job.status == RunStatus.held
    assert run.status == RunStatus.held


def test_credit_ceiling_holds_the_run(db: Session) -> None:
    def spends(db: Session, runner: StepRunner, payload: dict[str, Any]) -> None:
        assert runner.run_id
        db.add(Ledger(run_id=runner.run_id, provider=Provider.crustdata, endpoint="/x",
                      units=1000, unit_type=UnitType.credits))
        db.commit()
        ensure_budget(db, runner.run_id)

    HANDLERS["test_spends"] = spends
    run, job = _job(db, "test_spends", "ceiling-1")
    run_once(db, "w1")
    db.refresh(run)
    db.refresh(job)
    assert run.status == RunStatus.held
    assert run.hold_reason and "credits" in run.hold_reason
    assert job.status == RunStatus.held


def test_stale_running_jobs_are_requeued(db: Session) -> None:
    run, job = _job(db, "anything", "stale-1")
    job.status = RunStatus.running
    job.locked_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    assert queue.requeue_stale(db) == 1
    db.refresh(job)
    assert job.status == RunStatus.queued
