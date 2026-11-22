from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import InvestorId, current_investor_id
from app.errors import AUTH_RESPONSES
from app.models.enums import ProfileOrigin, ReviewStatus
from app.repositories import profiles
from app.schemas.profile import ProfileEdit, ScoringProfileOut

router = APIRouter(
    prefix="/scoring-profiles", tags=["scoring-profiles"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)
Db = Annotated[Session, Depends(get_db)]


@router.get("/{profile_id}", response_model=ScoringProfileOut)
def get_profile(profile_id: UUID, investor_id: InvestorId, db: Db) -> ScoringProfileOut:
    """The scoring profile, with `derivation` explaining each change from the generic one."""
    return profiles.to_out(profiles.get_owned(db, profile_id, investor_id))


@router.put("/{profile_id}", response_model=ScoringProfileOut)
def edit_profile(
    profile_id: UUID, body: ProfileEdit, investor_id: InvestorId, db: Db,
) -> ScoringProfileOut:
    """Save edits. Creates a **new version with a new id** (`origin: edited`, status
    `draft`). Weights must sum to 1 (422 otherwise)."""
    old = profiles.get_owned(db, profile_id, investor_id)
    new = profiles.create(
        db, investor_id=investor_id, thesis_id=old.thesis_id, origin=ProfileOrigin.edited,
        confidence=old.confidence, criteria=[c.model_dump() for c in body.criteria],
        thresholds=body.thresholds.model_dump(), self_reported_weight=body.self_reported_weight,
        source_tiers=body.source_tiers, derivation=old.derivation,
    )
    db.commit()
    return profiles.to_out(new)


@router.post("/{profile_id}/confirm", response_model=ScoringProfileOut)
def confirm_profile(profile_id: UUID, investor_id: InvestorId, db: Db) -> ScoringProfileOut:
    """Mark this version `confirmed`. Confirming a new version re-scores open candidates."""
    profile = profiles.get_owned(db, profile_id, investor_id)
    profile.status = ReviewStatus.confirmed
    db.commit()
    return profiles.to_out(profile)
