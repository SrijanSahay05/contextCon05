from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import (
    EX_CANDIDATE_ID,
    EX_CITATION,
    EX_MEMO_ID,
    Citation,
    examples,
)

EX_MEMO_CITATION = {"ref": 1, "fact_id": 48213, "claim_id": None, "citation": EX_CITATION}
EX_REMOVED = {
    "text": "Ledgerline is the market leader in GST tooling.",
    "reason": "No fact or claim supports this sentence",
}


class MemoCitation(BaseModel):
    """`[ref]` markers in the markdown point here. Exactly one of `fact_id` / `claim_id`."""

    ref: int
    fact_id: int | None
    claim_id: UUID | None
    citation: Citation

    model_config = examples(EX_MEMO_CITATION)


class RemovedSentence(BaseModel):
    """A sentence the checker dropped from the draft because it wasn't supported."""

    text: str
    reason: str

    model_config = examples(EX_REMOVED)


class MemoOut(BaseModel):
    """The investment memo. `stale` is true when the candidate was re-scored after it was
    generated (offer to regenerate)."""

    id: UUID
    candidate_id: UUID
    version: int
    markdown: str
    citations: list[MemoCitation]
    removed: list[RemovedSentence]
    stale: bool
    generated_at: datetime

    model_config = examples({
        "id": EX_MEMO_ID,
        "candidate_id": EX_CANDIDATE_ID,
        "version": 1,
        "markdown": "## Ledgerline\n\nGST reconciliation for Indian SMBs. Team grew to 42 [1].",
        "citations": [EX_MEMO_CITATION],
        "removed": [EX_REMOVED],
        "stale": False,
        "generated_at": "2026-11-22T09:00:00Z",
    })
