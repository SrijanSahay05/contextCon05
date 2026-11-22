"""What Scout does about a candidate: outreach, memos and ongoing watches."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.columns import created_at, enum_col, fk, uuid_pk
from app.models.enums import (
    OutreachChannel,
    OutreachStatus,
    SuggestedAction,
    WatchEventStatus,
    WatchReason,
)


class Outreach(Base):
    __tablename__ = "outreach"

    id: Mapped[uuid.UUID] = uuid_pk()
    candidate_id: Mapped[uuid.UUID] = fk("candidate.id")
    dd_request_id: Mapped[uuid.UUID | None] = fk(
        "dd_request.id", nullable=True, ondelete="SET NULL"
    )
    channel: Mapped[OutreachChannel] = enum_col(OutreachChannel)
    to_address: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[OutreachStatus] = enum_col(OutreachStatus, default=OutreachStatus.draft)
    # sending exactly once: the key travels as X-Scout-Outreach-Id for Sent-folder reconciliation
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    approved_by: Mapped[uuid.UUID | None] = fk("investor.id", nullable=True, ondelete="SET NULL")
    approved_at: Mapped[datetime | None]
    sent_at: Mapped[datetime | None]
    gmail_message_id: Mapped[str | None] = mapped_column(String(100))
    gmail_thread_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = created_at()


class Memo(Base):
    __tablename__ = "memo"
    __table_args__ = (UniqueConstraint("candidate_id", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    candidate_id: Mapped[uuid.UUID] = fk("candidate.id")
    version: Mapped[int] = mapped_column(Integer)
    markdown: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[Any]]
    removed: Mapped[list[Any]]
    stale: Mapped[bool] = mapped_column(default=False)
    generated_at: Mapped[datetime] = created_at()


class Watch(Base):
    __tablename__ = "watch"

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = fk("company.id")
    candidate_id: Mapped[uuid.UUID | None] = fk("candidate.id", nullable=True, ondelete="SET NULL")
    crustdata_watch_id: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[WatchReason] = enum_col(WatchReason)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = created_at()


class WatchEvent(Base):
    __tablename__ = "watch_event"

    id: Mapped[uuid.UUID] = uuid_pk()
    watch_id: Mapped[uuid.UUID] = fk("watch.id")
    source_id: Mapped[uuid.UUID | None] = fk("source.id", nullable=True, ondelete="SET NULL")
    changes: Mapped[list[Any]]
    suggested_action: Mapped[SuggestedAction | None] = enum_col(SuggestedAction, nullable=True)
    status: Mapped[WatchEventStatus] = enum_col(WatchEventStatus, default=WatchEventStatus.open)
    created_at: Mapped[datetime] = created_at()
