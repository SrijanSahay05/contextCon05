from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.enums import Confidence, ProfileOrigin, ReviewStatus
from app.schemas.common import (
    EX_DEAL_ID,
    EX_INVESTOR_ID,
    EX_PROFILE_ID,
    EX_THESIS_ID,
    examples,
)

EX_CRITERIA = [
    {"key": "thesis_fit", "weight": 0.25, "rule": "thesis_match", "params": {}},
    {"key": "team", "weight": 0.20, "rule": "team_signals", "params": {"use_pedigree": False}},
    {"key": "traction", "weight": 0.20, "rule": "growth_signals", "params": {"window_months": 6}},
    {"key": "funding", "weight": 0.10, "rule": "funding_stage_fit", "params": {}},
    {"key": "market", "weight": 0.15, "rule": "market_signals", "params": {}},
    {"key": "momentum", "weight": 0.10, "rule": "recent_events", "params": {"window_months": 6}},
]
EX_THRESHOLDS = {"reach_out": 65, "watch": 45, "min_completeness": 0.5}
EX_TIERS = {"A": 1.0, "B": 0.8, "C": 0.5}
EX_DERIVATION = {
    "target": "traction.weight",
    "change": "0.20 → 0.25",
    "reason": "9 of 14 deals were in companies that doubled headcount within a year",
    "evidence_ids": [EX_DEAL_ID],
}


class Criterion(BaseModel):
    """One scoring criterion. `rule` names a backend function; `params` tune it."""

    key: str
    weight: float = Field(ge=0, le=1)
    rule: str
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = examples(EX_CRITERIA[0])


class Thresholds(BaseModel):
    """Score cut-offs (0–100) for the suggested action, and the minimum completeness (0–1)
    before `reach_out` is suggested instead of `request_data`."""

    reach_out: float
    watch: float
    min_completeness: float = Field(ge=0, le=1)

    model_config = examples(EX_THRESHOLDS)


class DerivationStep(BaseModel):
    """Why the profile differs from the generic one. `evidence_ids` are deal ids (uuid) or
    fact ids, as strings."""

    target: str
    change: str
    reason: str
    evidence_ids: list[str]

    model_config = examples(EX_DERIVATION)


class ScoringProfileOut(BaseModel):
    """How candidates are scored for this partner. `origin: generic` means there were too
    few deals to derive one."""

    id: UUID
    investor_id: UUID
    thesis_id: UUID | None
    version: int
    status: ReviewStatus
    origin: ProfileOrigin
    confidence: Confidence
    criteria: list[Criterion]
    thresholds: Thresholds
    self_reported_weight: float
    source_tiers: dict[str, float]
    derivation: list[DerivationStep]
    created_at: datetime

    model_config = examples({
        "id": EX_PROFILE_ID,
        "investor_id": EX_INVESTOR_ID,
        "thesis_id": EX_THESIS_ID,
        "version": 1,
        "status": "draft",
        "origin": "derived",
        "confidence": "high",
        "criteria": EX_CRITERIA,
        "thresholds": EX_THRESHOLDS,
        "self_reported_weight": 0.5,
        "source_tiers": EX_TIERS,
        "derivation": [EX_DERIVATION],
        "created_at": "2026-11-20T09:21:00Z",
    })


class ProfileEdit(BaseModel):
    """Replaces the profile's criteria and thresholds. Weights must sum to 1."""

    criteria: list[Criterion] = Field(min_length=1)
    thresholds: Thresholds
    self_reported_weight: float = Field(default=0.5, ge=0, le=1)
    source_tiers: dict[str, float] = Field(default_factory=lambda: dict(EX_TIERS))

    model_config = examples({
        "criteria": EX_CRITERIA,
        "thresholds": EX_THRESHOLDS,
        "self_reported_weight": 0.5,
        "source_tiers": EX_TIERS,
    })

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> Self:
        if abs(sum(c.weight for c in self.criteria) - 1) > 0.001:
            raise ValueError("criteria weights must sum to 1")
        return self
