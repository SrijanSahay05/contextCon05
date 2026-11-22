"""Where every external call is recorded (source + ledger) and cached responses are found.

The database-backed recorder is written by the integrator; this module holds the
protocol and an in-memory fake for tests.
"""

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID


def request_hash(endpoint: str, body: Any) -> str:
    """sha256 of the endpoint plus the canonical JSON body, so key order doesn't matter."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((endpoint + canonical).encode()).hexdigest()


@dataclass(frozen=True)
class CachedResponse:
    source_id: UUID
    response: Any
    retrieved_at: datetime


class Recorder(Protocol):
    def lookup(self, request_hash: str, max_age: timedelta) -> CachedResponse | None:
        """Newest uncached response for this hash within `max_age`, if any."""
        ...

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
        run_id: UUID | None,
        kind: str,
        url: str | None = None,
        request_hash: str | None = None,
        credits_estimated: bool = False,
    ) -> UUID:
        """Store the call and its ledger row; return the source id.

        For `cached=True` the response already has a source, so only a ledger row is
        needed; the client keeps using the cached source id.
        """
        ...


@dataclass
class RecordedCall:
    provider: str
    endpoint: str
    request: dict[str, Any]
    response: Any
    units: float
    unit_type: str
    cached: bool
    run_id: UUID | None
    kind: str
    url: str | None
    request_hash: str | None
    credits_estimated: bool
    source_id: UUID
    retrieved_at: datetime


@dataclass
class InMemoryRecorder:
    """Recorder fake: keeps every call in `calls`."""

    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    calls: list[RecordedCall] = field(default_factory=list)

    def lookup(self, request_hash: str, max_age: timedelta) -> CachedResponse | None:
        cutoff = self.now() - max_age
        for call in reversed(self.calls):
            if call.request_hash == request_hash and not call.cached:
                if call.retrieved_at >= cutoff:
                    return CachedResponse(call.source_id, call.response, call.retrieved_at)
                return None
        return None

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
        run_id: UUID | None,
        kind: str,
        url: str | None = None,
        request_hash: str | None = None,
        credits_estimated: bool = False,
    ) -> UUID:
        source_id = uuid.uuid4()
        self.calls.append(
            RecordedCall(
                provider, endpoint, request, response, units, unit_type, cached, run_id,
                kind, url, request_hash, credits_estimated, source_id, self.now(),
            )
        )
        return source_id

    @property
    def total_units(self) -> float:
        return sum(c.units for c in self.calls)
