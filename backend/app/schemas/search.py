from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import CandidateStatus, DDStage, SearchStatus, SuggestedAction
from app.schemas.common import (
    EX_CANDIDATE_ID,
    EX_COMPANY_ID,
    EX_PROFILE_ID,
    EX_RUN_ID,
    EX_SEARCH_ID,
    EX_THESIS_ID,
    examples,
)

EX_CONDITION = {
    "field": "education.school",
    "op": "in",
    "value": ["BITS Pilani", "BITS Goa", "BITS Hyderabad"],
    "display": "Founder studied at BITS",
}
EX_FILTERS = {
    "people": [EX_CONDITION],
    "companies": [
        {"field": "industries", "op": "in", "value": ["Financial Services"],
         "display": "Fintech"},
        {"field": "hq_country", "op": "=", "value": "IND", "display": "HQ in India"},
    ],
    "funding": [
        {"field": "last_funding_round_type", "op": "in", "value": ["pre_seed", "seed"],
         "display": "Pre-seed or seed"},
    ],
    "grants": None,
    "window_months": 18,
}
EX_SUMMARY = {
    "id": EX_CANDIDATE_ID,
    "company_id": EX_COMPANY_ID,
    "company_name": "Ledgerline",
    "company_domain": "ledgerline.example.in",
    "one_liner": "GST reconciliation for Indian SMBs",
    "status": "new",
    "dd_stage": None,
    "score": 72.5,
    "completeness": 0.8,
    "suggested_action": "reach_out",
    "suggested_reason": "Strong thesis fit and headcount +60% in 6 months",
}


class Condition(BaseModel):
    """One filter chip. Render `display`; send the whole object back when editing."""

    field: str
    op: Literal["=", "in", ">", "<", "contains", "semantic"]
    value: Any
    display: str

    model_config = examples(EX_CONDITION)


class GrantFilter(BaseModel):
    """Require a (web-verified) grant, optionally from named programmes."""

    required: bool = True
    programs: list[str] = Field(default_factory=list)
    min_amount_usd: float | None = None

    model_config = examples({"required": True, "programs": ["BIRAC BIG"], "min_amount_usd": None})


class FilterSpec(BaseModel):
    """Structured search filters, as editable chips grouped by route."""

    people: list[Condition] = Field(default_factory=list)
    companies: list[Condition] = Field(default_factory=list)
    funding: list[Condition] = Field(default_factory=list)
    grants: GrantFilter | None = None
    window_months: int | None = Field(default=None, ge=1)

    model_config = examples(EX_FILTERS)


class Unresolved(BaseModel):
    """A query term that didn't match a Crustdata value; offer `suggestions` as choices."""

    term: str
    suggestions: list[str]

    model_config = examples({"term": "BITS", "suggestions": ["BITS Pilani", "BITS Goa"]})


class SearchCreate(BaseModel):
    """`as_of` (optional) runs the search as if on that date (backtesting)."""

    query: str = Field(min_length=3)
    as_of: date | None = None

    model_config = examples({
        "query": "pre-seed fintech in India with a BITS founder, raised in the last 18 months",
        "as_of": None,
    })


class CandidateSummary(BaseModel):
    """One row of the ranked results. `score` is null until scored."""

    id: UUID
    company_id: UUID
    company_name: str
    company_domain: str | None
    one_liner: str | None
    status: CandidateStatus
    dd_stage: DDStage | None
    score: float | None
    completeness: float | None
    suggested_action: SuggestedAction | None
    suggested_reason: str | None

    model_config = examples(EX_SUMMARY)


class SearchOut(BaseModel):
    """A search. While `status` is `draft`, show `parsed_filters` and `unresolved` for the
    partner to confirm. `candidates` is sorted by score (highest first)."""

    id: UUID
    query: str
    parsed_filters: FilterSpec
    unresolved: list[Unresolved]
    as_of: date | None
    thesis_id: UUID | None
    profile_id: UUID | None
    status: SearchStatus
    run_id: UUID | None
    created_at: datetime
    candidates: list[CandidateSummary] = Field(default_factory=list)

    model_config = examples({
        "id": EX_SEARCH_ID,
        "query": "pre-seed fintech in India with a BITS founder, raised in the last 18 months",
        "parsed_filters": EX_FILTERS,
        "unresolved": [],
        "as_of": None,
        "thesis_id": EX_THESIS_ID,
        "profile_id": EX_PROFILE_ID,
        "status": "done",
        "run_id": EX_RUN_ID,
        "created_at": "2026-11-21T10:00:00Z",
        "candidates": [EX_SUMMARY],
    })


class SearchList(BaseModel):
    """The investor's searches, newest first. `candidates` is empty in list items."""

    items: list[SearchOut]
    total: int

    model_config = examples({"items": [], "total": 0})
