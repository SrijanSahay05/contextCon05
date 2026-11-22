"""Searches, the candidates they found, and how each candidate was judged."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.columns import created_at, enum_col, fk, uuid_pk
from app.models.enums import (
    CandidateStatus,
    DDStage,
    QuestionStatus,
    SearchStatus,
    SignalKind,
    SnapshotTrigger,
    SuggestedAction,
)


class Search(Base):
    __tablename__ = "search"

    id: Mapped[uuid.UUID] = uuid_pk()
    investor_id: Mapped[uuid.UUID] = fk("investor.id")
    query_text: Mapped[str] = mapped_column(Text)
    parsed_filters: Mapped[dict[str, Any]]
    unresolved: Mapped[list[Any]]
    as_of: Mapped[date | None]
    thesis_id: Mapped[uuid.UUID | None] = fk("thesis.id", nullable=True, ondelete="SET NULL")
    profile_id: Mapped[uuid.UUID | None] = fk(
        "scoring_profile.id", nullable=True, ondelete="SET NULL"
    )
    status: Mapped[SearchStatus] = enum_col(SearchStatus, default=SearchStatus.draft)
    run_id: Mapped[uuid.UUID | None] = fk("run.id", nullable=True, ondelete="SET NULL")
    created_at: Mapped[datetime] = created_at()


class Candidate(Base):
    __tablename__ = "candidate"
    __table_args__ = (UniqueConstraint("search_id", "company_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    search_id: Mapped[uuid.UUID] = fk("search.id")
    company_id: Mapped[uuid.UUID] = fk("company.id")
    status: Mapped[CandidateStatus] = enum_col(CandidateStatus, default=CandidateStatus.new)
    dd_stage: Mapped[DDStage | None] = enum_col(DDStage, nullable=True)
    score: Mapped[float | None] = mapped_column(Numeric(6, 2))
    completeness: Mapped[float | None] = mapped_column(Numeric(4, 3))
    breakdown: Mapped[list[Any]]
    profile_version: Mapped[int | None] = mapped_column(Integer)
    suggested_action: Mapped[SuggestedAction | None] = enum_col(SuggestedAction, nullable=True)
    suggested_reason: Mapped[str | None] = mapped_column(Text)
    override: Mapped[dict[str, Any] | None]
    updated_at: Mapped[datetime] = created_at()


class Signal(Base):
    __tablename__ = "signal"

    id: Mapped[uuid.UUID] = uuid_pk()
    candidate_id: Mapped[uuid.UUID] = fk("candidate.id")
    kind: Mapped[SignalKind] = enum_col(SignalKind)
    text: Mapped[str] = mapped_column(Text)
    fact_ids: Mapped[list[Any]]
    claim_ids: Mapped[list[Any]]
    created_at: Mapped[datetime] = created_at()


class Question(Base):
    __tablename__ = "question"

    id: Mapped[uuid.UUID] = uuid_pk()
    candidate_id: Mapped[uuid.UUID] = fk("candidate.id")
    text: Mapped[str] = mapped_column(Text)
    motivated_by: Mapped[dict[str, Any]]
    status: Mapped[QuestionStatus] = enum_col(QuestionStatus, default=QuestionStatus.draft)
    answer_claim_id: Mapped[uuid.UUID | None] = fk("claim.id", nullable=True, ondelete="SET NULL")


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshot"

    id: Mapped[uuid.UUID] = uuid_pk()
    candidate_id: Mapped[uuid.UUID] = fk("candidate.id")
    score: Mapped[float | None] = mapped_column(Numeric(6, 2))
    completeness: Mapped[float | None] = mapped_column(Numeric(4, 3))
    breakdown: Mapped[list[Any]]
    profile_version: Mapped[int | None] = mapped_column(Integer)
    trigger: Mapped[SnapshotTrigger] = enum_col(SnapshotTrigger)
    delta: Mapped[list[Any]]
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = created_at()
