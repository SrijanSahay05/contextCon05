"""Fund, fund alias and onboarding-run lookups."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.enums import RunKind, StepStatus
from app.models.identity import Fund, FundAlias
from app.models.runs import Job, Run, RunStep

IDENTITY_JOB = "onboarding_identity"
ALIAS_STEP = "alias_candidates"


def get_fund(db: Session, fund_id: uuid.UUID) -> Fund:
    fund = db.get(Fund, fund_id)
    if fund is None:
        raise ApiError(404, ErrorCode.not_found, "Fund not found")
    return fund


def fund_for_company(
    db: Session, crustdata_company_id: int | None, name: str, domain: str | None
) -> Fund:
    """Reuse the fund with this Crustdata company id, or create it (race-safe)."""
    if crustdata_company_id is None:
        fund = Fund(name=name, domain=domain)
        db.add(fund)
        db.flush()
        return fund
    db.execute(
        insert(Fund)
        .values(id=uuid.uuid4(), name=name, domain=domain,
                crustdata_company_id=crustdata_company_id)
        .on_conflict_do_nothing(index_elements=["crustdata_company_id"])
    )
    existing = db.scalar(select(Fund).where(Fund.crustdata_company_id == crustdata_company_id))
    assert existing is not None
    return existing


def latest_run(db: Session, job_kind: str, **subject: str) -> Run | None:
    """The newest onboarding run with a job of `job_kind` whose subject contains `subject`."""
    return db.scalar(
        select(Run)
        .join(Job, Job.run_id == Run.id)
        .where(Run.kind == RunKind.onboarding, Job.kind == job_kind)
        .where(Run.subject.contains(subject))
        .order_by(Run.created_at.desc(), Job.id.desc())
        .limit(1)
    )


def alias_candidates(db: Session, fund_id: uuid.UUID) -> list[dict[str, Any]]:
    """The `alias_candidates` step output of the fund's latest identity run; 409 until done."""
    run = latest_run(db, IDENTITY_JOB, fund_id=str(fund_id))
    step = db.get(RunStep, (run.id, ALIAS_STEP)) if run else None
    if step is None or step.status != StepStatus.done:
        raise ApiError(409, ErrorCode.conflict, "Alias candidates are not ready yet",
                       {"run_id": str(run.id) if run else None})
    return list(step.output["candidates"])


def upsert_alias(
    db: Session, fund_id: uuid.UUID, permalink: str, canonical_name: str,
    investor_id: uuid.UUID, confirmed_at: datetime, source_id: uuid.UUID | None,
) -> None:
    values = dict(canonical_name=canonical_name, confirmed_by=investor_id,
                  confirmed_at=confirmed_at, source_id=source_id)
    db.execute(
        insert(FundAlias)
        .values(id=uuid.uuid4(), fund_id=fund_id, permalink=permalink, **values)
        .on_conflict_do_update(index_elements=["fund_id", "permalink"], set_=values)
    )


def has_aliases(db: Session, fund_id: uuid.UUID) -> bool:
    return db.scalar(select(FundAlias.id).where(FundAlias.fund_id == fund_id).limit(1)) is not None
