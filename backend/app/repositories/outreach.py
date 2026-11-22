"""Outreach rows, scoped to the investor who owns the candidate."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.actions import Outreach
from app.models.search import Candidate, Search
from app.schemas.outreach import OutreachOut


def get_owned(db: Session, outreach_id: uuid.UUID, investor_id: uuid.UUID) -> Outreach:
    row = db.execute(
        select(Outreach).join(Candidate, Candidate.id == Outreach.candidate_id)
        .join(Search, Search.id == Candidate.search_id)
        .where(Outreach.id == outreach_id, Search.investor_id == investor_id)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, ErrorCode.not_found, "Outreach not found")
    return row


def out(row: Outreach) -> OutreachOut:
    return OutreachOut(
        id=row.id, candidate_id=row.candidate_id, dd_request_id=row.dd_request_id,
        channel=row.channel, to_address=row.to_address, subject=row.subject, body=row.body,
        status=row.status, approved_by=row.approved_by, approved_at=row.approved_at,
        sent_at=row.sent_at, gmail_thread_id=row.gmail_thread_id,
    )
