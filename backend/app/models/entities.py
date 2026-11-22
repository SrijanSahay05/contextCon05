"""Startups and people, keyed by Crustdata ids so one entity is always one record."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.columns import created_at, fk, uuid_pk


class Company(Base):
    __tablename__ = "company"

    id: Mapped[uuid.UUID] = uuid_pk()
    crustdata_company_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    name: Mapped[str] = mapped_column(String(300))
    domain: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = created_at()


class Person(Base):
    __tablename__ = "person"

    id: Mapped[uuid.UUID] = uuid_pk()
    crustdata_person_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    name: Mapped[str] = mapped_column(String(300))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))


class CompanyPerson(Base):
    __tablename__ = "company_person"

    company_id: Mapped[uuid.UUID] = fk("company.id", primary_key=True)
    person_id: Mapped[uuid.UUID] = fk("person.id", primary_key=True)
    role: Mapped[str] = mapped_column(String(50), primary_key=True)
