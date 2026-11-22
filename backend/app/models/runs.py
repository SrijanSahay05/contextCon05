"""Background work: user-visible runs, their resumable steps, and the job queue."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.columns import bigint_pk, created_at, enum_col, fk, uuid_pk
from app.models.enums import RunKind, RunStatus, StepStatus


class Run(Base):
    __tablename__ = "run"

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[RunKind] = enum_col(RunKind)
    status: Mapped[RunStatus] = enum_col(RunStatus, default=RunStatus.queued)
    subject: Mapped[dict[str, Any]]
    credit_ceiling: Mapped[float] = mapped_column(Numeric(10, 2))
    credits_spent: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    deadline: Mapped[datetime]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)
    hold_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class RunStep(Base):
    """A finished step's output is reused on resume, so a step never runs twice."""

    __tablename__ = "run_step"

    run_id: Mapped[uuid.UUID] = fk("run.id", primary_key=True)
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer)
    status: Mapped[StepStatus] = enum_col(StepStatus)
    output: Mapped[Any] = mapped_column(JSONB, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None]


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = bigint_pk()
    run_id: Mapped[uuid.UUID | None] = fk("run.id", nullable=True)
    kind: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]]
    status: Mapped[RunStatus] = enum_col(RunStatus, default=RunStatus.queued)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    locked_at: Mapped[datetime | None]
    locked_by: Mapped[str | None] = mapped_column(String(100))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
