"""Crustdata API client: auth headers, client-side rate limits, retries, cache, credits."""

import random
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Any
from uuid import UUID

import httpx

from app.integrations import IntegrationSettings
from app.integrations.errors import (
    CreditsExhausted,
    CrustdataAuthError,
    CrustdataBadRequest,
    SourceUnavailable,
)
from app.integrations.recorder import Recorder, request_hash
from app.models.enums import Provider, SourceKind, UnitType

API_VERSION = "2025-11-01"
# Requests/minute per endpoint, a little under this key's limits from GET /account/endpoints
# (2026-11-22): search, enrich and identify are 5/min, autocomplete 300, social posts 100.
RATE_LIMITS = {"search": 5, "enrich": 5, "autocomplete": 250, "posts": 90, "web": 10,
               "watch": 10}
MAX_429_TRIES = 5
BACKOFF_5XX = (1.0, 2.0, 4.0)
MAX_RESET_WAIT = 30.0

Estimator = Callable[[dict[str, Any], Any], float]


@dataclass(frozen=True)
class CrustResult:
    data: Any
    source_id: UUID
    credits: float
    cached: bool
    credits_estimated: bool = False


class RateLimiter:
    """Sliding one-minute window: `acquire` sleeps until a slot is free."""

    def __init__(
        self, limit: int, clock: Callable[[], float], sleep: Callable[[float], None],
        window: float = 60.0,
    ) -> None:
        self.limit, self.window, self.clock, self.sleep = limit, window, clock, sleep
        self.sent: deque[float] = deque()

    def acquire(self) -> None:
        now = self.clock()
        while self.sent and self.sent[0] <= now - self.window:
            self.sent.popleft()
        if len(self.sent) >= self.limit:
            self.sleep(self.sent[0] + self.window - now)
            self.sent.popleft()
            now = self.clock()
        self.sent.append(now)


def _count(key: str, per: float) -> Estimator:
    """Estimate = `per` × number of items in `response[key]` (pricing-page list prices)."""
    return lambda _body, data: per * len((data or {}).get(key) or [])


def _matched(per: float) -> Estimator:
    """Estimate for enrich/identify: billed once per identifier that matched."""
    return lambda _body, data: per * sum(1 for m in (data or []) if m.get("matches"))


def _free(_body: dict[str, Any], _data: Any) -> float:
    return 0.0


class CrustdataBase:
    """Shared HTTP behaviour for the Crustdata data and web clients."""

    provider = Provider.crustdata

    def __init__(
        self,
        settings: IntegrationSettings,
        recorder: Recorder,
        transport: httpx.BaseTransport | None = None,
        run_id: UUID | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.recorder, self.run_id = recorder, run_id
        self.max_age = timedelta(hours=settings.cache_max_age_hours)
        self.clock, self.sleep, self.jitter = clock, sleep, jitter
        self.http = httpx.Client(
            base_url=settings.crustdata_base_url,
            transport=transport,
            timeout=60.0,
            headers={
                "authorization": f"Bearer {settings.crustdata_api_key or ''}",
                "x-api-version": API_VERSION,
                "content-type": "application/json",
            },
        )
        self.limiters: dict[str, RateLimiter] = {}

    def _limiter(self, endpoint: str, bucket: str) -> RateLimiter:
        if endpoint not in self.limiters:
            self.limiters[endpoint] = RateLimiter(RATE_LIMITS[bucket], self.clock, self.sleep)
        return self.limiters[endpoint]

    def _call(
        self,
        method: str,
        endpoint: str,
        body: dict[str, Any],
        *,
        bucket: str | None,
        estimate: Estimator,
        kind: str = SourceKind.crustdata,
        url: str | None = None,
        cacheable: bool = True,
    ) -> CrustResult:
        rhash = request_hash(endpoint, body)
        record = partial(
            self.recorder.record, provider=self.provider, endpoint=endpoint, request=body,
            unit_type=UnitType.credits, run_id=self.run_id, kind=kind, url=url,
            request_hash=rhash,
        )
        if cacheable and (hit := self.recorder.lookup(rhash, self.max_age)):
            record(response=hit.response, units=0.0, cached=True)
            return CrustResult(hit.response, hit.source_id, 0.0, cached=True)

        response = self._send(method, endpoint, body, bucket)
        data = response.json() if response.content else None
        header = response.headers.get("x-credits-used")
        estimated = header is None
        credits = estimate(body, data) if estimated else float(header)
        source_id = record(response=data, units=credits, cached=False, credits_estimated=estimated)
        return CrustResult(data, source_id, credits, cached=False, credits_estimated=estimated)

    def _send(
        self, method: str, endpoint: str, body: dict[str, Any], bucket: str | None
    ) -> httpx.Response:
        tries_429 = tries_5xx = 0
        while True:
            if bucket:
                self._limiter(endpoint, bucket).acquire()
            try:
                if method == "GET":
                    response = self.http.get(endpoint, params=body or None)
                else:
                    response = self.http.request(method, endpoint, json=body)
            except httpx.TransportError as exc:  # timeouts and connection errors
                failure: str = repr(exc)
            else:
                status = response.status_code
                if status < 400:
                    return response
                if status == 429:
                    tries_429 += 1
                    if tries_429 >= MAX_429_TRIES:
                        raise SourceUnavailable(f"{endpoint}: still rate limited after retries")
                    reset = float(response.headers.get("x-ratelimit-reset", 1))
                    self.sleep(min(reset, MAX_RESET_WAIT) + self.jitter())
                    continue
                if status < 500:
                    self._raise_client_error(response)
                failure = f"HTTP {status}"
            if tries_5xx >= len(BACKOFF_5XX):
                raise SourceUnavailable(f"{endpoint}: {failure}")
            self.sleep(BACKOFF_5XX[tries_5xx])
            tries_5xx += 1

    @staticmethod
    def _raise_client_error(response: httpx.Response) -> None:
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        status = response.status_code
        if status == 402:
            raise CreditsExhausted(str(body))
        if status in (401, 403):
            raise CrustdataAuthError(str(body))
        raise CrustdataBadRequest(status, body)


class CrustdataClient(CrustdataBase):
    """Typed entry points for the Crustdata data, watch and account APIs.

    Each method takes the request body as documented by Crustdata and returns the raw
    JSON in `CrustResult.data`.
    """

    def company_search(self, body: dict[str, Any]) -> CrustResult:
        return self._call("POST", "/company/search", body, bucket="search",
                          estimate=_count("companies", 0.03))

    def company_enrich(self, body: dict[str, Any]) -> CrustResult:
        return self._call("POST", "/company/enrich", body, bucket="enrich",
                          estimate=_matched(2.0))

    def company_identify(self, body: dict[str, Any]) -> CrustResult:
        return self._call("POST", "/company/identify", body, bucket="enrich",
                          estimate=_matched(0.2))

    def company_autocomplete(self, body: dict[str, Any]) -> CrustResult:
        return self._call("POST", "/company/search/autocomplete", body, bucket="autocomplete",
                          estimate=_free)

    def person_search(self, body: dict[str, Any]) -> CrustResult:
        return self._call("POST", "/person/search", body, bucket="search",
                          estimate=_count("profiles", 0.03))

    def person_enrich(self, body: dict[str, Any]) -> CrustResult:
        return self._call("POST", "/person/enrich", body, bucket="enrich",
                          estimate=_matched(1.0))

    def person_autocomplete(self, body: dict[str, Any]) -> CrustResult:
        return self._call("POST", "/person/search/autocomplete", body, bucket="autocomplete",
                          estimate=_free)

    def job_search(self, body: dict[str, Any]) -> CrustResult:
        return self._call("POST", "/job/search", body, bucket="search",
                          estimate=_count("job_listings", 0.03))

    def social_post_search(self, body: dict[str, Any]) -> CrustResult:
        return self._call("POST", "/social_post/search", body, bucket="posts",
                          estimate=_count("posts", 0.5))

    # Watches are charged per delivered change, not at create/test, so they estimate 0.
    def watch_company_create(self, body: dict[str, Any]) -> CrustResult:
        return self._call("POST", "/watch/company", body, bucket="watch", estimate=_free,
                          cacheable=False)

    def watch_test_notification(self, watch_id: int, body: dict[str, Any]) -> CrustResult:
        return self._call("POST", f"/watch/company/{watch_id}/test", body, bucket="watch",
                          estimate=_free, cacheable=False)

    def watch_runs(
        self, watch_id: int, limit: int | None = None, cursor: int | None = None
    ) -> CrustResult:
        params = {k: v for k, v in {"limit": limit, "cursor": cursor}.items() if v is not None}
        return self._call("GET", f"/watch/company/{watch_id}/runs", params, bucket="watch",
                          estimate=_free, cacheable=False)

    def credits_balance(self) -> CrustResult:
        """`GET /account/credits` (free; 300/min, so no client-side limiter)."""
        return self._call("GET", "/account/credits", {}, bucket=None, estimate=_free,
                          cacheable=False)
