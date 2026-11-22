"""Candidates of a search, and the company and founder facts scoring reads."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.entities import CompanyPerson
from app.models.enums import CandidateStatus, SubjectType
from app.models.evidence import Fact
from app.models.search import Candidate


def get_candidate(db: Session, candidate_id: uuid.UUID) -> Candidate | None:
    return db.get(Candidate, candidate_id)


def get_or_create_candidate(
    db: Session, search_id: uuid.UUID, company_id: uuid.UUID
) -> Candidate:
    """Idempotent per (search, company); a new row starts as `new`. Never commits."""
    db.execute(insert(Candidate).values(
        search_id=search_id, company_id=company_id, status=CandidateStatus.new, breakdown=[],
    ).on_conflict_do_nothing())
    candidate = db.scalar(select(Candidate).where(
        Candidate.search_id == search_id, Candidate.company_id == company_id))
    assert candidate is not None
    return candidate


def candidates_for_search(db: Session, search_id: uuid.UUID) -> Sequence[Candidate]:
    return db.scalars(
        select(Candidate).where(Candidate.search_id == search_id).order_by(Candidate.updated_at,
                                                                           Candidate.id)
    ).all()


def company_facts(
    db: Session, company_id: uuid.UUID, predicates: Sequence[str] | None = None
) -> Sequence[Fact]:
    """Facts about the company, oldest first, optionally only these predicates."""
    stmt = select(Fact).where(Fact.subject_type == SubjectType.company,
                              Fact.subject_id == company_id)
    if predicates is not None:
        stmt = stmt.where(Fact.predicate.in_(predicates))
    return db.scalars(stmt.order_by(Fact.id)).all()


def founder_facts(
    db: Session, company_id: uuid.UUID, predicates: Sequence[str] | None = None
) -> Sequence[Fact]:
    """Facts about every person linked to the company as `founder` (subject_id = person)."""
    founders = select(CompanyPerson.person_id).where(
        CompanyPerson.company_id == company_id, CompanyPerson.role == "founder")
    stmt = select(Fact).where(Fact.subject_type == SubjectType.person,
                              Fact.subject_id.in_(founders))
    if predicates is not None:
        stmt = stmt.where(Fact.predicate.in_(predicates))
    return db.scalars(stmt.order_by(Fact.subject_id, Fact.id)).all()
