"""Shared response pieces: the 202 body, and how every fact and claim cites its origin.

All sample data in the `examples` across `app.schemas` is fictional.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import ReliabilityTier, SourceKind, VerificationResult

# Fixed sample ids so examples across models point at each other consistently.
EX_INVESTOR_ID = "3f2b8c1e-6a4d-4e2f-9b1a-7c5d2e8f0a11"
EX_FUND_ID = "b7e1d4a2-0c3f-4a8b-8e6d-1f2a3b4c5d61"
EX_THESIS_ID = "c1a2b3c4-d5e6-4f70-8a9b-0c1d2e3f4a51"
EX_PROFILE_ID = "d4e5f6a7-b8c9-4d0e-9f1a-2b3c4d5e6f71"
EX_SEARCH_ID = "e5f6a7b8-c9d0-4e1f-8a2b-3c4d5e6f7a81"
EX_RUN_ID = "a9b8c7d6-e5f4-4a3b-9c2d-1e0f9a8b7c61"
EX_CANDIDATE_ID = "f1e2d3c4-b5a6-4978-8a6b-5c4d3e2f1a01"
EX_COMPANY_ID = "0a1b2c3d-4e5f-4a6b-9c7d-8e9f0a1b2c31"
EX_PERSON_ID = "1b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d41"
EX_SOURCE_ID = "2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e51"
EX_DEAL_ID = "3d4e5f6a-7b8c-4d9e-8f0a-2b3c4d5e6f61"
EX_CLAIM_ID = "4e5f6a7b-8c9d-4e0f-9a1b-3c4d5e6f7a71"
EX_DOCUMENT_ID = "5f6a7b8c-9d0e-4f1a-8b2c-4d5e6f7a8b81"
EX_OUTREACH_ID = "6a7b8c9d-0e1f-4a2b-9c3d-5e6f7a8b9c91"
EX_DD_REQUEST_ID = "7b8c9d0e-1f2a-4b3c-8d4e-6f7a8b9c0d01"
EX_MEMO_ID = "8c9d0e1f-2a3b-4c4d-9e5f-7a8b9c0d1e11"
EX_WATCH_ID = "9d0e1f2a-3b4c-4d5e-8f6a-8b9c0d1e2f21"
EX_WATCH_EVENT_ID = "0e1f2a3b-4c5d-4e6f-9a7b-9c0d1e2f3a31"

EX_CITATION: dict[str, Any] = {
    "source_id": EX_SOURCE_ID,
    "kind": "crustdata",
    "endpoint_or_url": "/screener/company",
    "retrieved_at": "2026-11-20T09:14:03Z",
    "locator": {"path": "headcount.linkedin_headcount_timeseries[11]"},
    "quote": None,
    "reliability_tier": "A",
}
EX_FACT: dict[str, Any] = {
    "id": 48213,
    "predicate": "headcount",
    "value": 42,
    "as_of": "2026-10-01",
    "citation": EX_CITATION,
}
EX_VERIFICATION: dict[str, Any] = {
    "id": "9a8b7c6d-5e4f-4a3b-8c2d-1e0f2a3b4c51",
    "claim_id": EX_CLAIM_ID,
    "result": "contradicted",
    "facts": [EX_FACT],
    "note": "Deck says 60 employees; LinkedIn headcount was 42 on 2026-10-01 (-30%).",
    "tolerance_used": {"pct": 0.15, "days": 60},
    "created_at": "2026-11-21T11:02:44Z",
}
EX_CLAIM: dict[str, Any] = {
    "id": EX_CLAIM_ID,
    "predicate": "headcount",
    "value": 60,
    "as_of": "2026-09-30",
    "page": 4,
    "quote": "A team of 60 across Bengaluru and Pune",
    "verification": EX_VERIFICATION,
}


def examples(*items: dict[str, Any]) -> ConfigDict:
    """`model_config` carrying OpenAPI examples."""
    return ConfigDict(json_schema_extra={"examples": list(items)})


class RunAccepted(BaseModel):
    """Returned with `202` by every long-running operation. Follow `events_url` (SSE) for
    live progress, or poll `status_url`."""

    run_id: UUID
    status_url: str
    events_url: str

    model_config = examples({
        "run_id": EX_RUN_ID,
        "status_url": f"/runs/{EX_RUN_ID}",
        "events_url": f"/runs/{EX_RUN_ID}/events",
    })


class Citation(BaseModel):
    """Where a fact or claim came from. `GET /sources/{source_id}` shows the raw snapshot;
    `locator` points inside it (`{path}` for JSON, `{page, quote}` for documents)."""

    source_id: UUID
    kind: SourceKind
    endpoint_or_url: str
    retrieved_at: datetime
    locator: dict[str, Any]
    quote: str | None = None
    reliability_tier: ReliabilityTier

    model_config = examples(EX_CITATION)


class FactOut(BaseModel):
    """Something an independent source says (Crustdata, web, news)."""

    id: int
    predicate: str
    value: Any
    as_of: date | None
    citation: Citation

    model_config = examples(EX_FACT)


class VerificationOut(BaseModel):
    """The check of one founder claim against independent facts. For `contradicted`, show
    the claim and `facts` side by side."""

    id: UUID
    claim_id: UUID
    result: VerificationResult
    facts: list[FactOut]
    note: str | None
    tolerance_used: dict[str, Any] | None
    created_at: datetime

    model_config = examples(EX_VERIFICATION)


class ClaimOut(BaseModel):
    """Something the founder states (deck, data room, email answer), with page and exact
    quote. `verification` is null until the claim has been checked."""

    id: UUID
    predicate: str
    value: Any
    as_of: date | None
    page: int | None
    quote: str
    verification: VerificationOut | None

    model_config = examples(EX_CLAIM)
