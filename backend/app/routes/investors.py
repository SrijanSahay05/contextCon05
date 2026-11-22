from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, ERROR_RESPONSES, not_implemented
from app.schemas.common import RunAccepted
from app.schemas.investor import ConfirmIdentity, IdentityCandidates, InvestorOut, OnboardRequest

router = APIRouter(prefix="/investors", tags=["investors"], responses=ERROR_RESPONSES)
_auth = [Depends(current_investor_id)]


@router.post("/onboard", response_model=IdentityCandidates, status_code=status.HTTP_201_CREATED)
def onboard(body: OnboardRequest) -> IdentityCandidates:
    """Start onboarding. No `X-Investor-Id` needed: this creates the investor.

    Returns the new `investor_id` (send it as `X-Investor-Id` from now on) and the
    Crustdata people who might be the partner, for an "Is this you?" screen.
    """
    not_implemented()


@router.post(
    "/{investor_id}/confirm-identity",
    response_model=RunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=_auth, responses=AUTH_RESPONSES,
)
def confirm_identity(investor_id: UUID, body: ConfirmIdentity) -> RunAccepted:
    """Confirm which person the partner is. Starts the onboarding run (finds the fund and
    its investor records). When the run ends, call `GET /investors/{id}` and continue with
    `GET /funds/{fund_id}/alias-candidates`."""
    not_implemented()


@router.get(
    "/{investor_id}", response_model=InvestorOut, dependencies=_auth,
    responses=AUTH_RESPONSES,
)
def get_investor(investor_id: UUID) -> InvestorOut:
    """The partner, their fund, and `onboarding_step` (which screen to show next)."""
    not_implemented()
