from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, ERROR_RESPONSES
from app.repositories.investors import get_investor as load_investor
from app.repositories.investors import investor_out
from app.schemas.common import RunAccepted
from app.schemas.investor import ConfirmIdentity, IdentityCandidates, InvestorOut, OnboardRequest
from app.services.onboarding import identity

router = APIRouter(prefix="/investors", tags=["investors"], responses=ERROR_RESPONSES)
_auth = [Depends(current_investor_id)]


@router.post("/onboard", response_model=IdentityCandidates, status_code=status.HTTP_201_CREATED)
def onboard(body: OnboardRequest, db: Session = Depends(get_db)) -> IdentityCandidates:
    """Start onboarding. No `X-Investor-Id` needed: this creates the investor.

    Returns the new `investor_id` (send it as `X-Investor-Id` from now on) and the
    Crustdata people who might be the partner, for an "Is this you?" screen.
    """
    return identity.onboard(db, body)


@router.post(
    "/{investor_id}/confirm-identity",
    response_model=RunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=_auth, responses=AUTH_RESPONSES,
)
def confirm_identity(
    investor_id: UUID, body: ConfirmIdentity, db: Session = Depends(get_db)
) -> RunAccepted:
    """Confirm which person the partner is. Starts the onboarding run (finds the fund and
    its investor records). When the run ends, call `GET /investors/{id}` and continue with
    `GET /funds/{fund_id}/alias-candidates`."""
    return identity.confirm_identity(db, investor_id, body.crustdata_person_id)


@router.get(
    "/{investor_id}", response_model=InvestorOut, dependencies=_auth,
    responses=AUTH_RESPONSES,
)
def get_investor(investor_id: UUID, db: Session = Depends(get_db)) -> InvestorOut:
    """The partner, their fund, and `onboarding_step` (which screen to show next)."""
    return investor_out(db, load_investor(db, investor_id))
