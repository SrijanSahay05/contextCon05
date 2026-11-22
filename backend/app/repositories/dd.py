"""DD requests, their checklist items and the request email, scoped to the investor."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.actions import Outreach
from app.models.dd import Claim, DDItem, DDRequest
from app.models.search import Candidate, Search


def get_owned_request(db: Session, request_id: uuid.UUID, investor_id: uuid.UUID) -> DDRequest:
    row = db.execute(
        select(DDRequest).join(Candidate, Candidate.id == DDRequest.candidate_id)
        .join(Search, Search.id == Candidate.search_id)
        .where(DDRequest.id == request_id, Search.investor_id == investor_id)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, ErrorCode.not_found, "DD request not found")
    return row


def latest_request(db: Session, candidate_id: uuid.UUID) -> DDRequest | None:
    return db.scalars(select(DDRequest).where(DDRequest.candidate_id == candidate_id)
                      .order_by(DDRequest.round.desc()).limit(1)).first()


def items(db: Session, request_id: uuid.UUID) -> Sequence[DDItem]:
    return db.scalars(select(DDItem).where(DDItem.dd_request_id == request_id)
                      .order_by(DDItem.kind, DDItem.id)).all()


def request_outreach(db: Session, request_id: uuid.UUID) -> Outreach | None:
    return db.scalars(select(Outreach).where(Outreach.dd_request_id == request_id)
                      .order_by(Outreach.created_at).limit(1)).first()


def document_claims(db: Session, document_id: uuid.UUID) -> Sequence[Claim]:
    return db.scalars(select(Claim).where(Claim.document_id == document_id)
                      .order_by(Claim.created_at, Claim.id)).all()
