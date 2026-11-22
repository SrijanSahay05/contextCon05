from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import InvestorId, current_investor_id
from app.errors import AUTH_RESPONSES, ApiError, ErrorCode, ErrorEnvelope, not_implemented
from app.repositories import dd as repo
from app.repositories import scores
from app.schemas.dd import DDOut
from app.services.dd import flow

router = APIRouter(
    tags=["dd"],
    responses={**AUTH_RESPONSES,
               409: {"model": ErrorEnvelope, "description": "Wrong stage for this action"}},
    dependencies=[Depends(current_investor_id)],
)
Db = Annotated[Session, Depends(get_db)]


@router.post(
    "/candidates/{candidate_id}/dd", response_model=DDOut, status_code=status.HTTP_201_CREATED
)
def start_dd(candidate_id: UUID, investor_id: InvestorId, db: Db) -> DDOut:
    """Start due diligence (or a second request round, max 2): the candidate moves to
    `in_dd`, Scout lists the missing items and drafts the request email
    (`stage: request_drafted`)."""
    request = flow.start(db, scores.get_owned(db, candidate_id, investor_id))
    db.commit()
    return flow.dd_out(db, request)


@router.get("/candidates/{candidate_id}/dd", response_model=DDOut)
def get_dd(candidate_id: UUID, investor_id: InvestorId, db: Db) -> DDOut:
    """The DD view for the current round: checklist, claims, verifications, mail thread,
    score history."""
    request = repo.latest_request(db, scores.get_owned(db, candidate_id, investor_id).id)
    if request is None:
        raise ApiError(404, ErrorCode.not_found, "No DD started for this candidate")
    return flow.dd_out(db, request)


@router.post("/dd/{request_id}/approve", response_model=DDOut)
def approve_dd(request_id: UUID, investor_id: InvestorId, db: Db) -> DDOut:
    """Approve the request email draft (edit it first with `PUT /outreach/{id}`)."""
    request = repo.get_owned_request(db, request_id, investor_id)
    flow.approve(db, request, investor_id)
    db.commit()
    return flow.dd_out(db, request)


@router.post("/dd/{request_id}/send", response_model=DDOut)
def send_dd(request_id: UUID, investor_id: InvestorId, db: Db) -> DDOut:
    """Send the approved request through Gmail: `stage → awaiting_founder`. Idempotent."""
    repo.get_owned_request(db, request_id, investor_id)
    not_implemented()


@router.post("/dd/{request_id}/mark-sent", response_model=DDOut)
def mark_dd_sent(request_id: UUID, investor_id: InvestorId, db: Db) -> DDOut:
    """The partner sent the request by hand (no Gmail): `stage → awaiting_founder`.
    Upload the founder's files with `POST /candidates/{id}/documents`."""
    request = repo.get_owned_request(db, request_id, investor_id)
    flow.mark_sent(db, request)
    db.commit()
    return flow.dd_out(db, request)
