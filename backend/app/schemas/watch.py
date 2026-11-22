from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import SuggestedAction, WatchEventStatus, WatchReason
from app.schemas.common import (
    EX_CANDIDATE_ID,
    EX_COMPANY_ID,
    EX_SOURCE_ID,
    EX_WATCH_EVENT_ID,
    EX_WATCH_ID,
    examples,
)

EX_CHANGE = {"field": "headcount", "before": 42, "after": 71, "summary": "Headcount +69%"}
EX_EVENT = {
    "id": EX_WATCH_EVENT_ID,
    "watch_id": EX_WATCH_ID,
    "candidate_id": EX_CANDIDATE_ID,
    "company_id": EX_COMPANY_ID,
    "company_name": "Ledgerline",
    "reason": "watch",
    "changes": [EX_CHANGE],
    "suggested_action": "reach_out",
    "suggested_reason": "Team grew 69% since you put it on watch",
    "status": "open",
    "source_id": EX_SOURCE_ID,
    "created_at": "2027-02-10T06:00:00Z",
}


class WatchChange(BaseModel):
    field: str
    before: Any
    after: Any
    summary: str

    model_config = examples(EX_CHANGE)


class WatchEventOut(BaseModel):
    """Something changed at a watched (or passed) company. `reason` is why it is watched."""

    id: UUID
    watch_id: UUID
    candidate_id: UUID
    company_id: UUID
    company_name: str
    reason: WatchReason
    changes: list[WatchChange]
    suggested_action: SuggestedAction | None
    suggested_reason: str | None
    status: WatchEventStatus
    source_id: UUID | None
    created_at: datetime

    model_config = examples(EX_EVENT)


class WatchEventList(BaseModel):
    items: list[WatchEventOut]
    total: int

    model_config = examples({"items": [EX_EVENT], "total": 1})
