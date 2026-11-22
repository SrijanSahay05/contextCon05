"""The VC side: investors (partners), their funds and the fund's confirmed investor records."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.columns import created_at, fk, uuid_pk


class Fund(Base):
    __tablename__ = "fund"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    crustdata_company_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    domain: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = created_at()


class Investor(Base):
    __tablename__ = "investor"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    linkedin_url: Mapped[str | None] = mapped_column(String(500), unique=True)
    crustdata_person_id: Mapped[int | None] = mapped_column(BigInteger)
    fund_id: Mapped[uuid.UUID | None] = fk("fund.id", nullable=True, ondelete="SET NULL")
    title: Mapped[str | None] = mapped_column(String(200))
    identity_confirmed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()


class FundAlias(Base):
    """A Crunchbase investor record the partner confirmed as their fund (handles lookalikes)."""

    __tablename__ = "fund_alias"
    __table_args__ = (UniqueConstraint("fund_id", "permalink"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    fund_id: Mapped[uuid.UUID] = fk("fund.id")
    permalink: Mapped[str] = mapped_column(String(200))
    canonical_name: Mapped[str] = mapped_column(String(200))
    confirmed_by: Mapped[uuid.UUID | None] = fk("investor.id", nullable=True, ondelete="SET NULL")
    confirmed_at: Mapped[datetime | None]
    source_id: Mapped[uuid.UUID | None] = fk("source.id", nullable=True, ondelete="SET NULL")


class InvestorPostLink(Base):
    """A partner's social post naming a portfolio company (the partner championed the deal)."""

    __tablename__ = "investor_post_link"

    investor_id: Mapped[uuid.UUID] = fk("investor.id", primary_key=True)
    company_id: Mapped[uuid.UUID] = fk("company.id", primary_key=True)
    source_id: Mapped[uuid.UUID] = fk("source.id", primary_key=True)
