import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import ExtractedBy, SourceKind, SubjectType
from app.models.evidence import Fact, Source


def _fact(source_id: uuid.UUID, subject_id: uuid.UUID) -> Fact:
    # as_of None on purpose: NULLS NOT DISTINCT must still treat these as duplicates
    return Fact(
        subject_type=SubjectType.company, subject_id=subject_id, predicate="industries",
        value=["deeptech"], as_of=None, source_id=source_id, locator={"path": "x"},
        extracted_by=ExtractedBy.rule,
    )


def test_the_database_rejects_a_duplicate_fact(db: Session) -> None:
    source = Source(kind=SourceKind.crustdata, endpoint_or_url="/company/enrich")
    db.add(source)
    db.flush()
    subject_id = uuid.uuid4()
    db.add(_fact(source.id, subject_id))
    db.commit()

    db.add(_fact(source.id, subject_id))
    with pytest.raises(IntegrityError):
        db.commit()
