from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, ErrorEnvelope, not_implemented
from app.schemas.candidate import CandidateOut, StatusChange
from app.schemas.common import RunAccepted

router = APIRouter(
    prefix="/candidates", tags=["candidates"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)


@router.get("/{candidate_id}", response_model=CandidateOut)
def get_candidate(candidate_id: UUID) -> CandidateOut:
    """Everything for the review screen: company, founders, score breakdown with cited
    facts and claims, signals, questions, suggested action and score history."""
    not_implemented()


@router.post(
    "/{candidate_id}/status",
    response_model=CandidateOut,
    responses={409: {"model": ErrorEnvelope, "description": "Transition not allowed"}},
)
def change_status(candidate_id: UUID, body: StatusChange) -> CandidateOut:
    """Move the candidate. Allowed: `new → shortlist | watch | pass`,
    `shortlist → watch | pass`, `in_dd → invest | watch | pass`, `watch → shortlist | pass`,
    `pass → watch`. `in_dd` is entered with `POST /candidates/{id}/dd`, not here.
    Anything else is 409 `not_allowed`. `invest` starts memo generation; `watch` and
    `pass` start a Crustdata watch."""
    not_implemented()


@router.post("/{candidate_id}/rescore", response_model=CandidateOut)
def rescore(candidate_id: UUID) -> CandidateOut:
    """Re-score from the facts and claims already collected (no new data, no credits)."""
    not_implemented()


@router.post(
    "/{candidate_id}/recheck", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED
)
def recheck(candidate_id: UUID) -> RunAccepted:
    """Fetch fresh data now ("re-check now"), then re-score. Spends credits."""
    not_implemented()
