"""Turn stored sources and facts into the API's `Citation`, `FactOut` and `SourceOut`."""

import uuid
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.database import Database
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.evidence import Fact, Source
from app.repositories.facts import get_fact
from app.repositories.sources import get_source
from app.schemas.common import Citation, FactOut
from app.schemas.source import SourceOut


def citation(source: Source, fact: Fact | None = None) -> Citation:
    """`locator`/`quote` come from the fact when given (a source alone has no locator)."""
    locator = dict(fact.locator) if fact else {}
    return Citation(
        source_id=source.id,
        kind=source.kind,
        endpoint_or_url=source.endpoint_or_url,
        retrieved_at=source.retrieved_at,
        locator=locator,
        quote=locator.get("quote"),
        reliability_tier=source.reliability_tier,
    )


def fact_out(db: Session, fact: Fact) -> FactOut:
    source = get_source(db, fact.source_id)
    assert source is not None  # fact.source_id is a non-null FK
    return FactOut(
        id=fact.id, predicate=fact.predicate, value=fact.value, as_of=fact.as_of,
        citation=citation(source, fact),
    )


def _raw_response(mongo: Database[dict[str, Any]], raw_id: str | None) -> Any:
    if raw_id is None:
        return None
    try:
        doc = mongo["raw"].find_one({"_id": ObjectId(raw_id)})
    except InvalidId:
        return None
    return doc.get("response") if doc else None


def source_out(
    db: Session,
    mongo: Database[dict[str, Any]],
    source_id: uuid.UUID,
    fact_id: int | None = None,
) -> SourceOut:
    """The source's citation plus its raw response payload; `fact_id` (which must cite
    this source) fills `citation.locator`/`quote` so the client can highlight it."""
    source = get_source(db, source_id)
    if source is None:
        raise ApiError(404, ErrorCode.not_found, "Source not found")
    fact = None
    if fact_id is not None:
        fact = get_fact(db, fact_id)
        if fact is None or fact.source_id != source.id:
            raise ApiError(404, ErrorCode.not_found, "Fact not found for this source",
                           {"fact_id": fact_id})
    return SourceOut(citation=citation(source, fact), raw=_raw_response(mongo, source.raw_id))
