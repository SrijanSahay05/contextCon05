import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import SubjectType
from app.models.evidence import Fact


def facts_for(
    db: Session, subject_type: SubjectType, subject_id: uuid.UUID, predicate: str | None = None
) -> Sequence[Fact]:
    """Facts about one subject, oldest first, optionally for one predicate."""
    stmt = select(Fact).where(Fact.subject_type == subject_type, Fact.subject_id == subject_id)
    if predicate is not None:
        stmt = stmt.where(Fact.predicate == predicate)
    return db.scalars(stmt.order_by(Fact.id)).all()


def get_fact(db: Session, fact_id: int) -> Fact | None:
    return db.get(Fact, fact_id)
