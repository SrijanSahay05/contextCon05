from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import Provider, RunKind, RunStatus, StepStatus, UnitType
from app.schemas.common import EX_RUN_ID, EX_SEARCH_ID, EX_SOURCE_ID, examples

EX_STEP = {
    "name": "collect_facts",
    "seq": 2,
    "status": "running",
    "attempt": 1,
    "output": None,
    "started_at": "2026-11-21T10:01:10Z",
    "finished_at": None,
}
EX_LEDGER = {
    "id": 90211,
    "provider": "crustdata",
    "endpoint": "/screener/company/search",
    "units": 0.75,
    "unit_type": "credits",
    "cached": False,
    "source_id": EX_SOURCE_ID,
    "created_at": "2026-11-21T10:01:12Z",
}


class RunStepOut(BaseModel):
    name: str
    seq: int
    status: StepStatus
    attempt: int
    output: dict[str, Any] | None
    started_at: datetime | None
    finished_at: datetime | None

    model_config = examples(EX_STEP)


class LedgerRowOut(BaseModel):
    """One metered call (Crustdata credits or LLM tokens). `cached` rows cost nothing."""

    id: int
    provider: Provider
    endpoint: str
    units: float
    unit_type: UnitType
    cached: bool
    source_id: UUID | None
    created_at: datetime

    model_config = examples(EX_LEDGER)


class RunOut(BaseModel):
    """A background run. `held` means it stopped and needs a person: show `hold_reason`.
    `ledger` is the last 50 rows, newest first."""

    id: UUID
    kind: RunKind
    status: RunStatus
    subject: dict[str, Any]
    credit_ceiling: float
    credits_spent: float
    deadline: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    hold_reason: str | None
    steps: list[RunStepOut]
    ledger: list[LedgerRowOut]

    model_config = examples({
        "id": EX_RUN_ID,
        "kind": "search",
        "status": "running",
        "subject": {"search_id": EX_SEARCH_ID},
        "credit_ceiling": 300,
        "credits_spent": 41.25,
        "deadline": "2026-11-21T10:21:00Z",
        "started_at": "2026-11-21T10:01:00Z",
        "finished_at": None,
        "error": None,
        "hold_reason": None,
        "steps": [EX_STEP],
        "ledger": [EX_LEDGER],
    })


class StepEvent(BaseModel):
    """Data of the SSE `step` event."""

    name: str
    status: StepStatus
    seq: int

    model_config = examples({"name": "collect_facts", "status": "done", "seq": 2})


class RunEvent(BaseModel):
    """Data of the SSE `run` event."""

    status: RunStatus
    credits_spent: float

    model_config = examples({"status": "running", "credits_spent": 41.25})
