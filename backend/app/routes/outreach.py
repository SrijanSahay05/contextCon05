from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, ErrorEnvelope, not_implemented
from app.schemas.outreach import OutreachCreate, OutreachEdit, OutreachOut

router = APIRouter(
    tags=["outreach"],
    responses={**AUTH_RESPONSES,
               409: {"model": ErrorEnvelope, "description": "Wrong status for this action"}},
    dependencies=[Depends(current_investor_id)],
)


@router.post(
    "/candidates/{candidate_id}/outreach",
    response_model=OutreachOut,
    status_code=status.HTTP_201_CREATED,
)
def create_outreach(candidate_id: UUID, body: OutreachCreate) -> OutreachOut:
    """Draft a message to the founders (status `draft`). Nothing is sent yet."""
    not_implemented()


@router.put("/outreach/{outreach_id}", response_model=OutreachOut)
def edit_outreach(outreach_id: UUID, body: OutreachEdit) -> OutreachOut:
    """Edit a `draft` message (also the DD request draft). 409 once approved."""
    not_implemented()


@router.post("/outreach/{outreach_id}/approve", response_model=OutreachOut)
def approve_outreach(outreach_id: UUID) -> OutreachOut:
    """The partner approves the text: `draft → approved`. Required before sending."""
    not_implemented()


@router.post("/outreach/{outreach_id}/send", response_model=OutreachOut)
def send_outreach(outreach_id: UUID) -> OutreachOut:
    """Send an `approved` email through the partner's Gmail: `approved → sending → sent`.
    Safe to retry (idempotent). Needs Gmail connected; otherwise use `mark-sent`."""
    not_implemented()


@router.post("/outreach/{outreach_id}/mark-sent", response_model=OutreachOut)
def mark_outreach_sent(outreach_id: UUID) -> OutreachOut:
    """The partner sent it by hand (copied text, LinkedIn): `approved → sent`."""
    not_implemented()
