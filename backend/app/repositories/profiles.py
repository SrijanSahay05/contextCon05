"""Scoring-profile persistence; every save is a new version."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.enums import Confidence, ProfileOrigin, ReviewStatus
from app.models.onboarding import ScoringProfile
from app.repositories.theses import next_version
from app.schemas.profile import ScoringProfileOut


def get_owned(db: Session, profile_id: uuid.UUID, investor_id: uuid.UUID) -> ScoringProfile:
    profile = db.get(ScoringProfile, profile_id)
    if profile is None or profile.investor_id != investor_id:
        raise ApiError(404, ErrorCode.not_found, "Scoring profile not found")
    return profile


def create(
    db: Session, *, investor_id: uuid.UUID, thesis_id: uuid.UUID | None,
    origin: ProfileOrigin, confidence: Confidence, criteria: list[dict[str, Any]],
    thresholds: dict[str, Any], self_reported_weight: float, source_tiers: dict[str, float],
    derivation: list[dict[str, Any]],
) -> ScoringProfile:
    profile = ScoringProfile(
        investor_id=investor_id, thesis_id=thesis_id,
        version=next_version(db, ScoringProfile, investor_id), status=ReviewStatus.draft,
        origin=origin, confidence=confidence, criteria=criteria, thresholds=thresholds,
        self_reported_weight=self_reported_weight, source_tiers=source_tiers,
        derivation=derivation,
    )
    db.add(profile)
    db.flush()
    return profile


def to_out(profile: ScoringProfile) -> ScoringProfileOut:
    return ScoringProfileOut(
        id=profile.id, investor_id=profile.investor_id, thesis_id=profile.thesis_id,
        version=profile.version, status=profile.status, origin=profile.origin,
        confidence=profile.confidence, criteria=profile.criteria,
        thresholds=profile.thresholds, self_reported_weight=float(profile.self_reported_weight),
        source_tiers=profile.source_tiers, derivation=profile.derivation,
        created_at=profile.created_at,
    )
