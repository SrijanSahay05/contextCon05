from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, not_implemented
from app.schemas.profile import ProfileEdit, ScoringProfileOut

router = APIRouter(
    prefix="/scoring-profiles", tags=["scoring-profiles"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)


@router.get("/{profile_id}", response_model=ScoringProfileOut)
def get_profile(profile_id: UUID) -> ScoringProfileOut:
    """The scoring profile, with `derivation` explaining each change from the generic one."""
    not_implemented()


@router.put("/{profile_id}", response_model=ScoringProfileOut)
def edit_profile(profile_id: UUID, body: ProfileEdit) -> ScoringProfileOut:
    """Save edits. Creates a **new version with a new id** (`origin: edited`, status
    `draft`). Weights must sum to 1 (422 otherwise)."""
    not_implemented()


@router.post("/{profile_id}/confirm", response_model=ScoringProfileOut)
def confirm_profile(profile_id: UUID) -> ScoringProfileOut:
    """Mark this version `confirmed`. Confirming a new version re-scores open candidates."""
    not_implemented()
