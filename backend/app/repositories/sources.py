import uuid

from sqlalchemy.orm import Session

from app.models.evidence import Source


def get_source(db: Session, source_id: uuid.UUID) -> Source | None:
    return db.get(Source, source_id)
