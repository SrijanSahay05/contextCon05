from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import (
    CandidateStatus,
    DDStage,
    QuestionStatus,
    SignalKind,
    SnapshotTrigger,
    SuggestedAction,
)
from app.schemas.common import (
    EX_CANDIDATE_ID,
    EX_CLAIM,
    EX_CLAIM_ID,
    EX_COMPANY_ID,
    EX_FACT,
    EX_INVESTOR_ID,
    EX_PERSON_ID,
    EX_SEARCH_ID,
    ClaimOut,
    FactOut,
    examples,
)

EX_COMPANY = {
    "id": EX_COMPANY_ID,
    "crustdata_company_id": 6619021,
    "name": "Ledgerline",
    "domain": "ledgerline.example.in",
    "one_liner": "GST reconciliation for Indian SMBs",
    "hq_location": "Bengaluru, India",
    "founded_year": 2024,
    "headcount": 42,
    "linkedin_url": "https://www.linkedin.com/company/ledgerline-example",
}
EX_FOUNDER = {
    "id": EX_PERSON_ID,
    "crustdata_person_id": 88120456,
    "name": "Rohan Mehta",
    "role": "Co-founder & CEO",
    "headline": "Ex-Razorpay | BITS Pilani",
    "linkedin_url": "https://www.linkedin.com/in/rohan-mehta-example",
}
EX_CRITERION_SCORE = {
    "key": "traction",
    "score": 78,
    "weight": 0.2,
    "reason": "Headcount 26 → 42 (+62%) in 6 months",
    "facts": [EX_FACT],
    "claims": [],
}
EX_SIGNAL = {
    "id": "aa11bb22-cc33-4d44-8e55-ff6677889901",
    "kind": "red_flag",
    "text": "Deck claims 60 employees; public headcount is 42",
    "fact_ids": [48213],
    "claim_ids": [EX_CLAIM_ID],
}
EX_QUESTION = {
    "id": "bb22cc33-dd44-4e55-8f66-007788990a12",
    "text": "Your deck says 60 people; public data shows 42 in October 2026. "
            "Can you share the current team list?",
    "motivated_by": {"type": "claim", "id": EX_CLAIM_ID},
    "status": "draft",
}
EX_SNAPSHOT = {
    "id": "cc33dd44-ee55-4f66-8a77-1188990a1b23",
    "score": 72.5,
    "completeness": 0.8,
    "profile_version": 1,
    "trigger": "initial",
    "delta": None,
    "created_at": "2026-11-21T10:04:00Z",
}


class CompanyOut(BaseModel):
    id: UUID
    crustdata_company_id: int | None
    name: str
    domain: str | None
    one_liner: str | None
    hq_location: str | None
    founded_year: int | None
    headcount: int | None
    linkedin_url: str | None

    model_config = examples(EX_COMPANY)


class FounderOut(BaseModel):
    id: UUID
    crustdata_person_id: int | None
    name: str
    role: str | None
    headline: str | None
    linkedin_url: str | None

    model_config = examples(EX_FOUNDER)


class CriterionScore(BaseModel):
    """One line of the score breakdown. `score` is 0–100 or `"unknown"` (no evidence;
    this is a gap). Every number cites `facts` (independent) or `claims` (founder)."""

    key: str
    score: float | Literal["unknown"]
    weight: float
    reason: str
    facts: list[FactOut]
    claims: list[ClaimOut]

    model_config = examples(EX_CRITERION_SCORE)


class SignalOut(BaseModel):
    """A strong signal, red flag or gap, with the facts and claims behind it."""

    id: UUID
    kind: SignalKind
    text: str
    fact_ids: list[int]
    claim_ids: list[UUID]

    model_config = examples(EX_SIGNAL)


class MotivatedBy(BaseModel):
    """What a follow-up question addresses. `id` is a fact id, claim/signal uuid, or a
    criterion key for a gap."""

    type: Literal["gap", "fact", "claim", "signal"]
    id: str

    model_config = examples({"type": "claim", "id": EX_CLAIM_ID})


class QuestionOut(BaseModel):
    id: UUID
    text: str
    motivated_by: MotivatedBy
    status: QuestionStatus

    model_config = examples(EX_QUESTION)


class ScoreSnapshotOut(BaseModel):
    """A point on the score history. `delta` describes what changed since the previous
    snapshot (per criterion), null for the first."""

    id: UUID
    score: float | None
    completeness: float | None
    profile_version: int
    trigger: SnapshotTrigger
    delta: dict[str, Any] | None
    created_at: datetime

    model_config = examples(EX_SNAPSHOT)


class OverrideOut(BaseModel):
    """The partner overrode Scout's suggestion."""

    by_investor_id: UUID
    action: str
    reason: str | None
    at: datetime

    model_config = examples({
        "by_investor_id": EX_INVESTOR_ID,
        "action": "shortlist",
        "reason": "Met the founder at a Pune meetup; strong product sense",
        "at": "2026-11-21T12:30:00Z",
    })


class CandidateOut(BaseModel):
    """Everything for the candidate review screen. `latest_memo_id` is set once a memo
    exists (`GET /memos/{memo_id}`)."""

    id: UUID
    search_id: UUID
    company: CompanyOut
    founders: list[FounderOut]
    status: CandidateStatus
    dd_stage: DDStage | None
    score: float | None
    completeness: float | None
    profile_version: int | None
    breakdown: list[CriterionScore]
    signals: list[SignalOut]
    questions: list[QuestionOut]
    suggested_action: SuggestedAction | None
    suggested_reason: str | None
    override: OverrideOut | None
    score_history: list[ScoreSnapshotOut]
    latest_memo_id: UUID | None
    updated_at: datetime

    model_config = examples({
        "id": EX_CANDIDATE_ID,
        "search_id": EX_SEARCH_ID,
        "company": EX_COMPANY,
        "founders": [EX_FOUNDER],
        "status": "shortlist",
        "dd_stage": None,
        "score": 72.5,
        "completeness": 0.8,
        "profile_version": 1,
        "breakdown": [EX_CRITERION_SCORE, {
            "key": "funding", "score": "unknown", "weight": 0.1,
            "reason": "No funding data found", "facts": [], "claims": [EX_CLAIM],
        }],
        "signals": [EX_SIGNAL],
        "questions": [EX_QUESTION],
        "suggested_action": "request_data",
        "suggested_reason": "Score is high but funding history is unknown",
        "override": None,
        "score_history": [EX_SNAPSHOT],
        "latest_memo_id": None,
        "updated_at": "2026-11-21T10:04:00Z",
    })


class StatusChange(BaseModel):
    """Move a candidate. `reason` is recorded when it overrides Scout's suggestion."""

    status: CandidateStatus
    reason: str | None = None

    model_config = examples({"status": "watch", "reason": "Too early; revisit after seed"})
