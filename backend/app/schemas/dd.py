from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import DDItemKind, DDItemStatus, DDStage, MailDirection
from app.schemas.candidate import EX_SNAPSHOT, ScoreSnapshotOut
from app.schemas.common import (
    EX_CANDIDATE_ID,
    EX_CLAIM,
    EX_DD_REQUEST_ID,
    EX_DOCUMENT_ID,
    EX_VERIFICATION,
    ClaimOut,
    VerificationOut,
    examples,
)
from app.schemas.outreach import EX_OUTREACH, OutreachOut

EX_ITEM = {
    "id": "dd11ee22-ff33-4a44-9b55-cc6677880011",
    "kind": "deck",
    "status": "received",
    "label": "Latest pitch deck",
    "document_id": EX_DOCUMENT_ID,
    "satisfied_by_message_id": None,
}
EX_MESSAGE = {
    "id": "ee22ff33-0a44-4b55-8c66-dd7788990022",
    "gmail_message_id": "18c2f1b0e5f6a7b8",
    "direction": "inbound",
    "received_at": "2026-11-23T07:41:00Z",
    "subject": "Re: Kestrel Ventures <> Ledgerline: a few documents",
    "snippet": "Hi Ananya, attached is our deck and the data room link...",
}


class DDItemOut(BaseModel):
    """One requested item on the DD checklist."""

    id: UUID
    kind: DDItemKind
    status: DDItemStatus
    label: str
    document_id: UUID | None
    satisfied_by_message_id: UUID | None

    model_config = examples(EX_ITEM)


class MailMessageOut(BaseModel):
    id: UUID
    gmail_message_id: str
    direction: MailDirection
    received_at: datetime | None
    subject: str | None
    snippet: str | None

    model_config = examples(EX_MESSAGE)


class DDThreadOut(BaseModel):
    gmail_thread_id: str
    messages: list[MailMessageOut]

    model_config = examples({"gmail_thread_id": "18c2f0a9d4e5b6c7", "messages": [EX_MESSAGE]})


class DDOut(BaseModel):
    """The DD screen. `request_id` is the id for `/dd/{id}/approve|send|mark-sent`.
    `request` is the request email draft (edit it with `PUT /outreach/{id}`). `round` is
    1 or 2. Dates are when a reminder is drafted and when the candidate times out to
    `watch`."""

    request_id: UUID
    candidate_id: UUID
    round: int
    stage: DDStage
    request: OutreachOut | None
    items: list[DDItemOut]
    claims: list[ClaimOut]
    verifications: list[VerificationOut]
    thread: DDThreadOut | None
    score_history: list[ScoreSnapshotOut]
    reminder_due_at: datetime | None
    timeout_at: datetime | None

    model_config = examples({
        "request_id": EX_DD_REQUEST_ID,
        "candidate_id": EX_CANDIDATE_ID,
        "round": 1,
        "stage": "verifying",
        "request": {**EX_OUTREACH, "dd_request_id": EX_DD_REQUEST_ID, "status": "sent"},
        "items": [EX_ITEM],
        "claims": [EX_CLAIM],
        "verifications": [EX_VERIFICATION],
        "thread": {"gmail_thread_id": "18c2f0a9d4e5b6c7", "messages": [EX_MESSAGE]},
        "score_history": [EX_SNAPSHOT],
        "reminder_due_at": None,
        "timeout_at": "2026-12-05T13:00:00Z",
    })
