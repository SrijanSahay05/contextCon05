from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import OutreachChannel, OutreachStatus
from app.schemas.common import EX_CANDIDATE_ID, EX_INVESTOR_ID, EX_OUTREACH_ID, examples

EX_OUTREACH = {
    "id": EX_OUTREACH_ID,
    "candidate_id": EX_CANDIDATE_ID,
    "dd_request_id": None,
    "channel": "email",
    "to_address": "rohan@ledgerline.example.in",
    "subject": "Kestrel Ventures <> Ledgerline",
    "body": "Hi Rohan,\n\nI lead fintech investing at Kestrel Ventures. Ledgerline's growth "
            "since June caught our eye. Would you have 30 minutes next week?\n\nAnanya",
    "status": "draft",
    "approved_by": None,
    "approved_at": None,
    "sent_at": None,
    "gmail_thread_id": None,
}


class OutreachCreate(BaseModel):
    """Draft a message. `call_request` asks for an intro call; `follow_up` chases a
    previous message. (DD data requests are drafted by `POST /candidates/{id}/dd`.)"""

    channel: OutreachChannel
    purpose: Literal["call_request", "follow_up"]

    model_config = examples({"channel": "email", "purpose": "call_request"})


class OutreachEdit(BaseModel):
    """Only fields you send are changed. Only `draft` messages can be edited."""

    to_address: str | None = None
    subject: str | None = None
    body: str | None = None

    model_config = examples({"subject": "Intro: Kestrel Ventures x Ledgerline"})


class OutreachOut(BaseModel):
    """A drafted or sent message. Nothing is sent without `approve` first."""

    id: UUID
    candidate_id: UUID
    dd_request_id: UUID | None
    channel: OutreachChannel
    to_address: str | None
    subject: str | None
    body: str
    status: OutreachStatus
    approved_by: UUID | None
    approved_at: datetime | None
    sent_at: datetime | None
    gmail_thread_id: str | None

    model_config = examples(EX_OUTREACH, {
        **EX_OUTREACH,
        "status": "sent",
        "approved_by": EX_INVESTOR_ID,
        "approved_at": "2026-11-21T13:00:00Z",
        "sent_at": "2026-11-21T13:00:05Z",
        "gmail_thread_id": "18c2f0a9d4e5b6c7",
    })
