from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, ErrorEnvelope, not_implemented
from app.schemas.dd import DDOut

router = APIRouter(
    tags=["dd"],
    responses={**AUTH_RESPONSES,
               409: {"model": ErrorEnvelope, "description": "Wrong stage for this action"}},
    dependencies=[Depends(current_investor_id)],
)


@router.post(
    "/candidates/{candidate_id}/dd", response_model=DDOut, status_code=status.HTTP_201_CREATED
)
def start_dd(candidate_id: UUID) -> DDOut:
    """Start due diligence (or a second request round, max 2): the candidate moves to
    `in_dd`, Scout lists the missing items and drafts the request email
    (`stage: request_drafted`)."""
    not_implemented()


@router.get("/candidates/{candidate_id}/dd", response_model=DDOut)
def get_dd(candidate_id: UUID) -> DDOut:
    """The DD view for the current round: checklist, claims, verifications, mail thread,
    score history."""
    not_implemented()


@router.post("/dd/{request_id}/approve", response_model=DDOut)
def approve_dd(request_id: UUID) -> DDOut:
    """Approve the request email draft (edit it first with `PUT /outreach/{id}`)."""
    not_implemented()


@router.post("/dd/{request_id}/send", response_model=DDOut)
def send_dd(request_id: UUID) -> DDOut:
    """Send the approved request through Gmail: `stage → awaiting_founder`. Idempotent."""
    not_implemented()


@router.post("/dd/{request_id}/mark-sent", response_model=DDOut)
def mark_dd_sent(request_id: UUID) -> DDOut:
    """The partner sent the request by hand (no Gmail): `stage → awaiting_founder`.
    Upload the founder's files with `POST /candidates/{id}/documents`."""
    not_implemented()
