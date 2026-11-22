"""Watches and the events they produce; events are scoped to an investor through
watch → candidate → search."""

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.actions import Watch, WatchEvent
from app.models.entities import Company
from app.models.enums import WatchEventStatus, WatchReason
from app.models.search import Candidate, Search


def find_watch(
    db: Session, company_id: uuid.UUID, reason: WatchReason,
    candidate_id: uuid.UUID | None = None,
) -> Watch | None:
    """A watch for (company, reason); with `candidate_id`, that candidate's own row."""
    stmt = select(Watch).where(Watch.company_id == company_id, Watch.reason == reason)
    if candidate_id is not None:
        stmt = stmt.where(Watch.candidate_id == candidate_id)
    return db.scalars(stmt.order_by(Watch.created_at).limit(1)).first()


def watch_for_candidate(db: Session, candidate_id: uuid.UUID) -> Watch | None:
    return db.scalars(select(Watch).where(Watch.candidate_id == candidate_id)
                      .order_by(Watch.created_at.desc()).limit(1)).first()


def watches_matching(
    db: Session, crustdata_watch_id: int | None, crustdata_company_ids: Sequence[int]
) -> Sequence[Watch]:
    """Active watches by Crustdata watch id or by the watched companies' Crustdata ids."""
    conditions = []
    if crustdata_watch_id is not None:
        conditions.append(Watch.crustdata_watch_id == crustdata_watch_id)
    if crustdata_company_ids:
        conditions.append(Watch.company_id.in_(select(Company.id).where(
            Company.crustdata_company_id.in_(crustdata_company_ids))))
    if not conditions:
        return []
    return db.scalars(select(Watch).where(Watch.status == "active", or_(*conditions))
                      .order_by(Watch.created_at)).all()


def _owned(investor_id: uuid.UUID) -> Select[WatchEvent, Watch, Company]:
    return (select(WatchEvent, Watch, Company)
            .join(Watch, Watch.id == WatchEvent.watch_id)
            .join(Candidate, Candidate.id == Watch.candidate_id)
            .join(Search, Search.id == Candidate.search_id)
            .join(Company, Company.id == Watch.company_id)
            .where(Search.investor_id == investor_id))


def list_events(
    db: Session, investor_id: uuid.UUID, status: WatchEventStatus | None, limit: int, offset: int
) -> tuple[list[tuple[WatchEvent, Watch, Company]], int]:
    stmt = _owned(investor_id)
    if status is not None:
        stmt = stmt.where(WatchEvent.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(WatchEvent.created_at.desc(), WatchEvent.id)
                      .limit(limit).offset(offset)).all()
    return list(rows), total


def get_owned_event(
    db: Session, event_id: uuid.UUID, investor_id: uuid.UUID
) -> tuple[WatchEvent, Watch, Company]:
    row = db.execute(_owned(investor_id).where(WatchEvent.id == event_id)).first()
    if row is None:
        raise ApiError(404, ErrorCode.not_found, "Watch event not found")
    return row
