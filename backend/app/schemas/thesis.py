from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import Confidence, ReviewStatus
from app.schemas.common import (
    EX_COMPANY_ID,
    EX_DEAL_ID,
    EX_FUND_ID,
    EX_INVESTOR_ID,
    EX_SOURCE_ID,
    EX_THESIS_ID,
    examples,
)

ThesisDimension = Literal[
    "sectors", "stage", "check_size", "geography", "entry_profile", "trend",
    "partner_lens", "exclusion",
]

EX_POINT = {
    "dimension": "sectors",
    "statement": "71% of deals are fintech or B2B SaaS",
    "value": {"fintech": 0.43, "b2b_saas": 0.28, "agritech": 0.14, "other": 0.15},
    "deal_ids": [EX_DEAL_ID],
}
EX_DEAL = {
    "id": EX_DEAL_ID,
    "company_id": EX_COMPANY_ID,
    "company_name": "Paysetu",
    "company_domain": "paysetu.example.in",
    "round_date": "2026-03-14",
    "round_type": "seed",
    "amount_usd": 2500000.0,
    "led": True,
    "match_rule": "exact_permalink",
    "championed_by_investor_id": EX_INVESTOR_ID,
    "source_id": EX_SOURCE_ID,
}


class ThesisPoint(BaseModel):
    """One computed point of the thesis. `value` depends on `dimension` (shares per
    sector/stage/country, `{median_usd, min_usd, max_usd, lead_share}` for check size,
    a string for an exclusion). `deal_ids` are the deals behind it (show as citations)."""

    dimension: ThesisDimension
    statement: str
    value: Any
    deal_ids: list[UUID] = Field(default_factory=list)

    model_config = examples(EX_POINT, {
        "dimension": "check_size",
        "statement": "Median cheque $2.0M (range $0.8M–$4.5M); led 9 of 14 deals",
        "value": {"median_usd": 2000000, "min_usd": 800000, "max_usd": 4500000,
                  "lead_share": 0.64},
        "deal_ids": [EX_DEAL_ID],
    })


class ThesisWindow(BaseModel):
    start: date
    end: date

    model_config = examples({"start": "2024-11-01", "end": "2026-11-01"})


class DealOut(BaseModel):
    """A round the fund took part in. `match_rule` says how it was tied to the fund."""

    id: UUID
    company_id: UUID
    company_name: str
    company_domain: str | None
    round_date: date | None
    round_type: str | None
    amount_usd: float | None
    led: bool | None
    match_rule: str
    championed_by_investor_id: UUID | None
    source_id: UUID

    model_config = examples(EX_DEAL)


class ThesisOut(BaseModel):
    """The inferred (or edited) thesis. `confidence` is `low` with fewer than 5 deals; show
    a warning then. `summary` is LLM prose built only from `points`."""

    id: UUID
    investor_id: UUID
    fund_id: UUID
    version: int
    status: ReviewStatus
    window: ThesisWindow
    deal_count: int
    confidence: Confidence
    points: list[ThesisPoint]
    summary: str | None
    deals: list[DealOut]
    created_at: datetime

    model_config = examples({
        "id": EX_THESIS_ID,
        "investor_id": EX_INVESTOR_ID,
        "fund_id": EX_FUND_ID,
        "version": 1,
        "status": "draft",
        "window": {"start": "2024-11-01", "end": "2026-11-01"},
        "deal_count": 14,
        "confidence": "high",
        "points": [EX_POINT],
        "summary": "Kestrel backs seed-stage fintech and B2B SaaS in Bengaluru, usually "
                   "leading with a ~$2M cheque.",
        "deals": [EX_DEAL],
        "created_at": "2026-11-20T09:20:00Z",
    })


class AddedDeal(BaseModel):
    """A deal Scout missed, added by the partner. `url` is the source (press release etc)."""

    company_name: str
    url: str
    round_type: str | None = None
    round_date: date | None = None
    amount_usd: float | None = None

    model_config = examples({
        "company_name": "Kirana Cloud",
        "url": "https://news.example.in/kirana-cloud-raises-seed",
        "round_type": "seed",
        "round_date": "2025-08-02",
        "amount_usd": 1800000.0,
    })


class ThesisEdit(BaseModel):
    """`points` replaces the full list (add exclusions as `dimension: "exclusion"`)."""

    points: list[ThesisPoint]
    added_deals: list[AddedDeal] = Field(default_factory=list)
    removed_deal_ids: list[UUID] = Field(default_factory=list)

    model_config = examples({
        "points": [EX_POINT, {"dimension": "exclusion", "statement": "No crypto or lending",
                              "value": "crypto, lending", "deal_ids": []}],
        "added_deals": [],
        "removed_deal_ids": [],
    })
