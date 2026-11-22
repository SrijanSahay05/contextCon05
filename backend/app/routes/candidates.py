from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import InvestorId, current_investor_id
from app.errors import AUTH_RESPONSES, ErrorEnvelope
from app.models.enums import SnapshotTrigger
from app.repositories import scores
from app.schemas.candidate import CandidateOut, StatusChange
from app.schemas.common import RunAccepted
from app.services.actions import status as status_service
from app.services.scoring.service import score_candidate
from app.services.watch.recheck_job import daily_key, start_recheck

router = APIRouter(
    prefix="/candidates", tags=["candidates"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)
Db = Annotated[Session, Depends(get_db)]


@router.get("/{candidate_id}", response_model=CandidateOut)
def get_candidate(candidate_id: UUID, investor_id: InvestorId, db: Db) -> CandidateOut:
    """Everything for the review screen: company, founders, score breakdown with cited
    facts and claims, signals, questions, suggested action and score history."""
    return scores.candidate_out(db, scores.get_owned(db, candidate_id, investor_id))


@router.post(
    "/{candidate_id}/status",
    response_model=CandidateOut,
    responses={409: {"model": ErrorEnvelope, "description": "Transition not allowed"}},
)
def change_status(
    candidate_id: UUID, body: StatusChange, investor_id: InvestorId, db: Db
) -> CandidateOut:
    """Move the candidate. Allowed: `new → shortlist | watch | pass`,
    `shortlist → watch | pass`, `in_dd → invest | watch | pass`, `watch → shortlist | pass`,
    `pass → watch`. `in_dd` is entered with `POST /candidates/{id}/dd`, not here.
    Anything else is 409 `not_allowed`. `invest` starts memo generation; `watch` and
    `pass` start a Crustdata watch."""
    candidate = status_service.change_status(db, investor_id, candidate_id, body)
    db.commit()
    return scores.candidate_out(db, candidate)


@router.post("/{candidate_id}/rescore", response_model=CandidateOut)
def rescore(candidate_id: UUID, investor_id: InvestorId, db: Db) -> CandidateOut:
    """Re-score from the facts and claims already collected (no new data, no credits)."""
    scores.get_owned(db, candidate_id, investor_id)
    # a manual re-score picks up profile or thesis edits; new data has its own triggers
    candidate = score_candidate(db, candidate_id, SnapshotTrigger.profile_change)
    db.commit()
    return scores.candidate_out(db, candidate)


@router.post(
    "/{candidate_id}/recheck", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED
)
def recheck(candidate_id: UUID, investor_id: InvestorId, db: Db) -> RunAccepted:
    """Fetch fresh data now ("re-check now"), then re-score. Spends credits."""
    candidate = scores.get_owned(db, candidate_id, investor_id)
    return start_recheck(db, candidate, investor_id, daily_key(candidate.id))
