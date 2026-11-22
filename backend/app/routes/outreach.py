from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import InvestorId, current_investor_id
from app.errors import AUTH_RESPONSES, ErrorEnvelope, not_implemented
from app.repositories import outreach as repo
from app.schemas.outreach import OutreachCreate, OutreachEdit, OutreachOut
from app.services.actions import outreach as service

router = APIRouter(
    tags=["outreach"],
    responses={**AUTH_RESPONSES,
               409: {"model": ErrorEnvelope, "description": "Wrong status for this action"}},
    dependencies=[Depends(current_investor_id)],
)
Db = Annotated[Session, Depends(get_db)]


@router.post(
    "/candidates/{candidate_id}/outreach",
    response_model=OutreachOut,
    status_code=status.HTTP_201_CREATED,
)
def create_outreach(
    candidate_id: UUID, body: OutreachCreate, investor_id: InvestorId, db: Db
) -> OutreachOut:
    """Draft a message to the founders (status `draft`). Nothing is sent yet."""
    row = service.create(db, investor_id, candidate_id, body)
    db.commit()
    return repo.out(row)


@router.put("/outreach/{outreach_id}", response_model=OutreachOut)
def edit_outreach(
    outreach_id: UUID, body: OutreachEdit, investor_id: InvestorId, db: Db
) -> OutreachOut:
    """Edit a message (also the DD request draft). Editing an `approved` message sends it
    back to `draft`, so the changed text must be approved again. 409 once sent."""
    row = service.edit(db, investor_id, outreach_id, body)
    db.commit()
    return repo.out(row)


@router.post("/outreach/{outreach_id}/approve", response_model=OutreachOut)
def approve_outreach(outreach_id: UUID, investor_id: InvestorId, db: Db) -> OutreachOut:
    """The partner approves the text: `draft → approved`. Required before sending."""
    row = service.approve(db, investor_id, outreach_id)
    db.commit()
    return repo.out(row)


@router.post("/outreach/{outreach_id}/send", response_model=OutreachOut)
def send_outreach(outreach_id: UUID, investor_id: InvestorId, db: Db) -> OutreachOut:
    """Send an `approved` email through the partner's Gmail: `approved → sending → sent`.
    Safe to retry (idempotent). Needs Gmail connected; otherwise use `mark-sent`."""
    repo.get_owned(db, outreach_id, investor_id)
    not_implemented()


@router.post("/outreach/{outreach_id}/mark-sent", response_model=OutreachOut)
def mark_outreach_sent(outreach_id: UUID, investor_id: InvestorId, db: Db) -> OutreachOut:
    """The partner sent it by hand (copied text, LinkedIn): `approved → sent`."""
    row = service.mark_sent(db, investor_id, outreach_id)
    db.commit()
    return repo.out(row)
