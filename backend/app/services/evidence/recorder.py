"""Database-backed Recorder: raw payload → Mongo `raw`, plus `source` and `ledger` rows.

It commits in its own session, so a ledger row survives even when the calling step
rolls back: money spent is never forgotten.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from pymongo.database import Database
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.recorder import CachedResponse
from app.models.enums import Provider, ReliabilityTier, SourceKind, UnitType
from app.models.evidence import Ledger, Source

TIERS = {
    SourceKind.crustdata: ReliabilityTier.a,
    SourceKind.news: ReliabilityTier.b,
    SourceKind.web: ReliabilityTier.c,
}


class DbRecorder:
    def __init__(
        self, session_factory: Callable[[], Session], mongo: Database[dict[str, Any]]
    ) -> None:
        self.session_factory = session_factory
        self.raw = mongo["raw"]
        # one LLM call reports input and output tokens separately; both share one source
        self._llm_source: uuid.UUID | None = None

    def lookup(self, request_hash: str, max_age: timedelta) -> CachedResponse | None:
        with self.session_factory() as db:
            source = db.scalar(
                select(Source)
                .where(Source.request_hash == request_hash)
                .where(Source.retrieved_at >= datetime.now(UTC) - max_age)
                .order_by(Source.retrieved_at.desc())
                .limit(1)
            )
            if source is None or source.raw_id is None:
                return None
            doc = self.raw.find_one({"_id": ObjectId(source.raw_id)})
            if doc is None:
                return None
            return CachedResponse(source.id, doc["response"], source.retrieved_at)

    def record(
        self,
        *,
        provider: str,
        endpoint: str,
        request: dict[str, Any],
        response: Any,
        units: float,
        unit_type: str,
        cached: bool,
        run_id: uuid.UUID | None,
        kind: str,
        url: str | None = None,
        request_hash: str | None = None,
        credits_estimated: bool = False,
    ) -> uuid.UUID:
        with self.session_factory() as db:
            source_id = self._source_for(
                db, provider, endpoint, request, response, unit_type, cached, run_id, kind,
                url, request_hash,
            )
            db.add(
                Ledger(
                    run_id=run_id,
                    provider=Provider(provider),
                    endpoint=endpoint,
                    units=units,
                    unit_type=UnitType(unit_type),
                    estimated=credits_estimated,
                    request_hash=request_hash,
                    source_id=source_id,
                    cached=cached,
                )
            )
            db.commit()
            return source_id

    def _source_for(
        self,
        db: Session,
        provider: str,
        endpoint: str,
        request: dict[str, Any],
        response: Any,
        unit_type: str,
        cached: bool,
        run_id: uuid.UUID | None,
        kind: str,
        url: str | None,
        request_hash: str | None,
    ) -> uuid.UUID:
        if cached and request_hash:
            existing = db.scalar(
                select(Source.id)
                .where(Source.request_hash == request_hash)
                .order_by(Source.retrieved_at.desc())
                .limit(1)
            )
            if existing:
                return existing
        if provider == Provider.llm and unit_type == UnitType.output_tokens and self._llm_source:
            source_id, self._llm_source = self._llm_source, None
            return source_id

        source_kind = SourceKind(kind)
        source = Source(
            kind=source_kind,
            endpoint_or_url=url or endpoint,
            request_hash=request_hash,
            reliability_tier=TIERS.get(source_kind, ReliabilityTier.c),
            run_id=run_id,
        )
        db.add(source)
        db.flush()
        inserted = self.raw.insert_one(
            {
                "source_id": str(source.id),
                "provider": provider,
                "endpoint": endpoint,
                "url": url,
                "request": request,
                "response": response,
                "retrieved_at": datetime.now(UTC),
            }
        )
        source.raw_id = str(inserted.inserted_id)
        if provider == Provider.llm:
            self._llm_source = source.id
        return source.id
