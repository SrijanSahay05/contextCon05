from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, not_implemented
from app.schemas.thesis import ThesisEdit, ThesisOut

router = APIRouter(
    prefix="/theses", tags=["theses"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)


@router.get("/{thesis_id}", response_model=ThesisOut)
def get_thesis(thesis_id: UUID) -> ThesisOut:
    """The thesis with its points and the deals behind them."""
    not_implemented()


@router.put("/{thesis_id}", response_model=ThesisOut)
def edit_thesis(thesis_id: UUID, body: ThesisEdit) -> ThesisOut:
    """Save the partner's edits. Every save creates a **new version with a new id**
    (status `draft`); use the returned `id` from then on."""
    not_implemented()


@router.post("/{thesis_id}/confirm", response_model=ThesisOut)
def confirm_thesis(thesis_id: UUID) -> ThesisOut:
    """Mark this version `confirmed`. New searches use the latest confirmed thesis."""
    not_implemented()
