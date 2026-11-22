"""Search persistence and the `SearchOut` view (with ranked candidates)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.entities import Company
from app.models.enums import ReviewStatus
from app.models.onboarding import ScoringProfile, Thesis
from app.models.search import Candidate, Search
from app.schemas.search import CandidateSummary, FilterSpec, SearchOut, Unresolved


def get_owned(db: Session, search_id: uuid.UUID, investor_id: uuid.UUID) -> Search:
    search = db.get(Search, search_id)
    if search is None or search.investor_id != investor_id:
        raise ApiError(404, ErrorCode.not_found, "Search not found")
    return search


def latest_confirmed[T: (Thesis, ScoringProfile)](
    db: Session, model: type[T], investor_id: uuid.UUID
) -> T | None:
    return db.scalar(
        select(model)
        .where(model.investor_id == investor_id, model.status == ReviewStatus.confirmed)
        .order_by(model.version.desc()).limit(1)
    )


def list_owned(
    db: Session, investor_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[Search], int]:
    where = Search.investor_id == investor_id
    total = db.scalar(select(func.count()).select_from(Search).where(where)) or 0
    rows = db.scalars(
        select(Search).where(where).order_by(Search.created_at.desc(), Search.id)
        .limit(limit).offset(offset)
    ).all()
    return list(rows), total


def _float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def candidates(db: Session, search_id: uuid.UUID) -> list[CandidateSummary]:
    rows = db.execute(
        select(Candidate, Company).join(Company, Company.id == Candidate.company_id)
        .where(Candidate.search_id == search_id)
        .order_by(Candidate.score.desc().nulls_last(), Company.name)
    ).all()
    return [
        CandidateSummary(
            id=c.id, company_id=co.id, company_name=co.name, company_domain=co.domain,
            one_liner=None, status=c.status, dd_stage=c.dd_stage, score=_float(c.score),
            completeness=_float(c.completeness), suggested_action=c.suggested_action,
            suggested_reason=c.suggested_reason,
        )
        for c, co in rows
    ]


def to_out(db: Session, search: Search, with_candidates: bool = False) -> SearchOut:
    return SearchOut(
        id=search.id, query=search.query_text,
        parsed_filters=FilterSpec.model_validate(search.parsed_filters),
        unresolved=[Unresolved.model_validate(u) for u in search.unresolved],
        as_of=search.as_of, thesis_id=search.thesis_id, profile_id=search.profile_id,
        status=search.status, run_id=search.run_id, created_at=search.created_at,
        candidates=candidates(db, search.id) if with_candidates else [],
    )
