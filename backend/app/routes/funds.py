from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import InvestorId, current_investor_id
from app.errors import AUTH_RESPONSES
from app.repositories import funds as fund_repo
from app.schemas.common import RunAccepted
from app.schemas.fund import AliasCandidate, ConfirmAliases
from app.services.onboarding import firm

router = APIRouter(
    prefix="/funds", tags=["funds"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)


@router.get("/{fund_id}/alias-candidates", response_model=list[AliasCandidate])
def alias_candidates(fund_id: UUID, db: Session = Depends(get_db)) -> list[AliasCandidate]:
    """Crustdata investor records that might be this fund (name variants, e.g. "Kestrel
    Ventures" vs "Kestrel Capital"). Show them as a checklist with `preselected` ticked."""
    fund_repo.get_fund(db, fund_id)
    return [AliasCandidate(**c) for c in fund_repo.alias_candidates(db, fund_id)]


@router.post(
    "/{fund_id}/aliases", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED
)
def confirm_aliases(
    fund_id: UUID, body: ConfirmAliases, investor_id: InvestorId, db: Session = Depends(get_db)
) -> RunAccepted:
    """Confirm which records are the fund. Continues onboarding: collects deals, then
    builds the draft thesis and scoring profile. When the run is `done`,
    `GET /investors/{id}` has `current_thesis_id` and `current_profile_id`."""
    return firm.confirm_aliases(db, fund_id, investor_id, body.permalinks)
