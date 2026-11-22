"""Due diligence: what was requested, what the founder sent, and how each claim checked out."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.columns import created_at, enum_col, fk, uuid_pk
from app.models.enums import (
    DDItemKind,
    DDItemStatus,
    DocumentOrigin,
    MailDirection,
    ParseStatus,
    VerificationResult,
)


class DDRequest(Base):
    __tablename__ = "dd_request"

    id: Mapped[uuid.UUID] = uuid_pk()
    candidate_id: Mapped[uuid.UUID] = fk("candidate.id")
    round: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="open")
    upload_token_hash: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (UniqueConstraint("candidate_id", "sha256"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    candidate_id: Mapped[uuid.UUID] = fk("candidate.id")
    kind: Mapped[DDItemKind] = enum_col(DDItemKind)
    origin: Mapped[DocumentOrigin] = enum_col(DocumentOrigin)
    storage_path: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    parse_status: Mapped[ParseStatus] = enum_col(ParseStatus, default=ParseStatus.pending)
    page_count: Mapped[int | None] = mapped_column(Integer)
    source_id: Mapped[uuid.UUID | None] = fk("source.id", nullable=True, ondelete="SET NULL")
    created_at: Mapped[datetime] = created_at()


class DDItem(Base):
    __tablename__ = "dd_item"

    id: Mapped[uuid.UUID] = uuid_pk()
    dd_request_id: Mapped[uuid.UUID] = fk("dd_request.id")
    kind: Mapped[DDItemKind] = enum_col(DDItemKind)
    status: Mapped[DDItemStatus] = enum_col(DDItemStatus, default=DDItemStatus.requested)
    reason: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = fk("document.id", nullable=True, ondelete="SET NULL")
    satisfied_by_message_id: Mapped[uuid.UUID | None] = fk(
        "mail_message.id", nullable=True, ondelete="SET NULL"
    )


class Claim(Base):
    """Something the founder stated; counts as verified only when a fact confirms it."""

    __tablename__ = "claim"

    id: Mapped[uuid.UUID] = uuid_pk()
    candidate_id: Mapped[uuid.UUID] = fk("candidate.id")
    document_id: Mapped[uuid.UUID | None] = fk("document.id", nullable=True)
    message_id: Mapped[uuid.UUID | None] = fk("mail_message.id", nullable=True)
    page: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)
    predicate: Mapped[str] = mapped_column(String(100))
    value: Mapped[Any] = mapped_column(JSONB)
    as_of: Mapped[date | None]
    created_at: Mapped[datetime] = created_at()


class Verification(Base):
    __tablename__ = "verification"

    id: Mapped[uuid.UUID] = uuid_pk()
    claim_id: Mapped[uuid.UUID] = fk("claim.id")
    result: Mapped[VerificationResult] = enum_col(VerificationResult)
    fact_ids: Mapped[list[Any]]
    note: Mapped[str | None] = mapped_column(Text)
    tolerance_used: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime] = created_at()


class MailAccount(Base):
    __tablename__ = "mail_account"

    id: Mapped[uuid.UUID] = uuid_pk()
    investor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investor.id", ondelete="CASCADE"), unique=True
    )
    email: Mapped[str] = mapped_column(String(320))
    refresh_token_enc: Mapped[str] = mapped_column(Text)
    history_id: Mapped[str | None] = mapped_column(String(50))
    scopes: Mapped[list[Any]]
    status: Mapped[str] = mapped_column(String(32), default="connected")


class MailThread(Base):
    __tablename__ = "mail_thread"

    id: Mapped[uuid.UUID] = uuid_pk()
    dd_request_id: Mapped[uuid.UUID] = fk("dd_request.id")
    gmail_thread_id: Mapped[str] = mapped_column(String(100), unique=True)


class MailMessage(Base):
    __tablename__ = "mail_message"

    id: Mapped[uuid.UUID] = uuid_pk()
    mail_thread_id: Mapped[uuid.UUID] = fk("mail_thread.id")
    gmail_message_id: Mapped[str] = mapped_column(String(100), unique=True)
    direction: Mapped[MailDirection] = enum_col(MailDirection)
    received_at: Mapped[datetime | None]
    processed_at: Mapped[datetime | None]
    raw_id: Mapped[str | None] = mapped_column(String(64))
