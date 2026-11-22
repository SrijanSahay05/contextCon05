from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, not_implemented
from app.schemas.common import RunAccepted
from app.schemas.fund import AliasCandidate, ConfirmAliases

router = APIRouter(
    prefix="/funds", tags=["funds"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)


@router.get("/{fund_id}/alias-candidates", response_model=list[AliasCandidate])
def alias_candidates(fund_id: UUID) -> list[AliasCandidate]:
    """Crustdata investor records that might be this fund (name variants, e.g. "Kestrel
    Ventures" vs "Kestrel Capital"). Show them as a checklist with `preselected` ticked."""
    not_implemented()


@router.post(
    "/{fund_id}/aliases", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED
)
def confirm_aliases(fund_id: UUID, body: ConfirmAliases) -> RunAccepted:
    """Confirm which records are the fund. Continues onboarding: collects deals, then
    builds the draft thesis and scoring profile. When the run is `done`,
    `GET /investors/{id}` has `current_thesis_id` and `current_profile_id`."""
    not_implemented()
