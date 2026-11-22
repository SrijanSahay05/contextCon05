"""Where every fact came from, the facts themselves, and what each call cost."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.columns import bigint_pk, created_at, enum_col, fk, uuid_pk
from app.models.enums import (
    ExtractedBy,
    Provider,
    ReliabilityTier,
    SourceKind,
    SubjectType,
    UnitType,
)


class Source(Base):
    """One retrieved record; its raw payload lives unmodified in Mongo `raw`."""

    __tablename__ = "source"

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[SourceKind] = enum_col(SourceKind)
    endpoint_or_url: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    retrieved_at: Mapped[datetime] = created_at()
    raw_id: Mapped[str | None] = mapped_column(String(64))
    reliability_tier: Mapped[ReliabilityTier] = enum_col(ReliabilityTier, default=ReliabilityTier.a)
    run_id: Mapped[uuid.UUID | None] = fk("run.id", nullable=True, ondelete="SET NULL")


class Fact(Base):
    """An independently sourced statement about a subject, true as of `as_of`."""

    __tablename__ = "fact"
    __table_args__ = (
        Index("ix_fact_subject_predicate", "subject_type", "subject_id", "predicate"),
    )

    id: Mapped[int] = bigint_pk()
    subject_type: Mapped[SubjectType] = enum_col(SubjectType)
    subject_id: Mapped[uuid.UUID]
    predicate: Mapped[str] = mapped_column(String(100))
    value: Mapped[Any] = mapped_column(JSONB)
    as_of: Mapped[date | None]
    observed_at: Mapped[datetime] = created_at()
    source_id: Mapped[uuid.UUID] = fk("source.id")
    locator: Mapped[dict[str, Any]]
    extracted_by: Mapped[ExtractedBy] = enum_col(ExtractedBy)


class Ledger(Base):
    __tablename__ = "ledger"

    id: Mapped[int] = bigint_pk()
    run_id: Mapped[uuid.UUID | None] = fk("run.id", nullable=True, ondelete="SET NULL")
    provider: Mapped[Provider] = enum_col(Provider)
    endpoint: Mapped[str] = mapped_column(String(200))
    units: Mapped[float] = mapped_column(Numeric(12, 4))
    unit_type: Mapped[UnitType] = enum_col(UnitType)
    estimated: Mapped[bool] = mapped_column(default=False)
    request_hash: Mapped[str | None] = mapped_column(String(64))
    source_id: Mapped[uuid.UUID | None] = fk("source.id", nullable=True, ondelete="SET NULL")
    cached: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = created_at()
