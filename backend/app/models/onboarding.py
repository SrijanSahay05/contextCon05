"""The fund's verified deals, the inferred thesis and the derived scoring profile."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.columns import created_at, enum_col, fk, uuid_pk
from app.models.enums import Confidence, ProfileOrigin, ReviewStatus


class Deal(Base):
    """A funding round that names the fund, matched strictly against a confirmed alias."""

    __tablename__ = "deal"
    __table_args__ = (UniqueConstraint("fund_id", "company_id", "round_date", "round_type"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    fund_id: Mapped[uuid.UUID] = fk("fund.id")
    company_id: Mapped[uuid.UUID] = fk("company.id")
    round_date: Mapped[date | None]
    round_type: Mapped[str | None] = mapped_column(String(50))
    amount_usd: Mapped[float | None] = mapped_column(Numeric(16, 2))
    led: Mapped[bool | None]
    match_rule: Mapped[str] = mapped_column(String(50))
    match_evidence: Mapped[dict[str, Any]]
    championed_by_investor_id: Mapped[uuid.UUID | None] = fk(
        "investor.id", nullable=True, ondelete="SET NULL"
    )
    source_id: Mapped[uuid.UUID] = fk("source.id")


class Thesis(Base):
    __tablename__ = "thesis"
    __table_args__ = (UniqueConstraint("investor_id", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    investor_id: Mapped[uuid.UUID] = fk("investor.id")
    fund_id: Mapped[uuid.UUID] = fk("fund.id")
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[ReviewStatus] = enum_col(ReviewStatus, default=ReviewStatus.draft)
    window_start: Mapped[date | None]
    window_end: Mapped[date | None]
    deal_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[Confidence] = enum_col(Confidence)
    points: Mapped[list[Any]]
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class ScoringProfile(Base):
    __tablename__ = "scoring_profile"
    __table_args__ = (UniqueConstraint("investor_id", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    investor_id: Mapped[uuid.UUID] = fk("investor.id")
    thesis_id: Mapped[uuid.UUID | None] = fk("thesis.id", nullable=True, ondelete="SET NULL")
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[ReviewStatus] = enum_col(ReviewStatus, default=ReviewStatus.draft)
    origin: Mapped[ProfileOrigin] = enum_col(ProfileOrigin)
    confidence: Mapped[Confidence] = enum_col(Confidence)
    criteria: Mapped[list[Any]]
    thresholds: Mapped[dict[str, Any]]
    self_reported_weight: Mapped[float] = mapped_column(Numeric(4, 3), default=0.5)
    source_tiers: Mapped[dict[str, Any]]
    derivation: Mapped[list[Any]]
    created_at: Mapped[datetime] = created_at()
