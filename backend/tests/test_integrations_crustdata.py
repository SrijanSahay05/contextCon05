import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.integrations.crustdata import CrustdataClient
from app.integrations.errors import (
    CreditsExhausted,
    CrustdataAuthError,
    CrustdataBadRequest,
    SourceUnavailable,
)
from app.integrations.recorder import InMemoryRecorder, request_hash

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return data


@dataclass
class FakeSettings:
    crustdata_api_key: str | None = "test-key"
    crustdata_base_url: str = "https://crust.test"
    openrouter_api_key: str | None = "or-test-key"
    openrouter_base_url: str = "https://openrouter.test/api/v1"
    llm_model: str = "anthropic/claude-sonnet-5.5"
    llm_fast_model: str = "anthropic/claude-haiku-5.5"
    cache_max_age_hours: float = 24


@dataclass
class FakeTime:
    """Injected clock + sleep: sleeping advances the clock instantly."""

    now: float = 1000.0
    sleeps: list[float] = field(default_factory=list)

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


Handler = Callable[[httpx.Request], httpx.Response]


def replay(name: str) -> httpx.Response:
    fx = fixture(name)
    return httpx.Response(200, json=fx["response"], headers=fx["headers"])


def make(
    handler: Handler, recorder: InMemoryRecorder | None = None
) -> tuple[CrustdataClient, InMemoryRecorder, FakeTime]:
    recorder = recorder or InMemoryRecorder()
    time = FakeTime()
    client = CrustdataClient(
        FakeSettings(), recorder, transport=httpx.MockTransport(handler),
        clock=time.clock, sleep=time.sleep, jitter=lambda: 0.5,
    )
    return client, recorder, time


def test_company_enrich_sends_headers_and_reads_credit_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return replay("crustdata/company_enrich")

    client, recorder, _ = make(handler)
    fx = fixture("crustdata/company_enrich")
    result = client.company_enrich(fx["request"])

    request = seen[0]
    assert request.url.path == "/company/enrich"
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["x-api-version"] == "2025-11-01"
    assert json.loads(request.content) == fx["request"]
    assert result.credits == 2.0 and not result.credits_estimated and not result.cached
    [call] = recorder.calls
    assert call.source_id == result.source_id
    assert call.request_hash == request_hash("/company/enrich", fx["request"])
    assert call.units == 2.0 and call.unit_type == "credits" and call.kind == "crustdata"


def test_company_enrich_fixture_has_accel_scenario() -> None:
    company = fixture("crustdata/company_enrich")["response"][0]["matches"][0]["company_data"]
    rounds = company["funding"]["milestones"]
    names = [[n.strip() for n in r["investors"].split(",")] for r in rounds]
    assert len(rounds) == 6
    assert sum("Accel" in n for n in names) == 2
    assert sum("Accel-KKR" in n for n in names) == 1
    permalinks = {i["permalink"] for i in company["funding"]["investors_detailed"]}
    assert {"accel", "accel-kkr"} <= permalinks
    assert len(company["headcount"]["timeseries"]) > 1


def test_missing_credit_header_is_estimated_from_pricing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fixture("crustdata/company_search")["response"])

    client, recorder, _ = make(handler)
    result = client.company_search({"limit": 2})

    assert result.credits == pytest.approx(0.06)
    assert result.credits_estimated and recorder.calls[0].credits_estimated


def test_retries_429_using_reset_header() -> None:
    responses = [
        httpx.Response(429, headers={"x-ratelimit-reset": "7"}),
        httpx.Response(429, headers={"x-ratelimit-reset": "120"}),
        replay("crustdata/person_search"),
    ]
    client, _, time = make(lambda _: responses.pop(0))

    result = client.person_search({"limit": 1})

    assert result.data["total_count"] == 1
    assert time.sleeps == [7.5, 30.5]  # reset + jitter, capped at 30 s


def test_gives_up_after_five_429s() -> None:
    calls: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, headers={"x-ratelimit-reset": "1"})

    client, _, _ = make(handler)
    with pytest.raises(SourceUnavailable):
        client.job_search({})
    assert len(calls) == 5


def test_gives_up_after_repeated_5xx_with_backoff() -> None:
    calls: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    client, recorder, time = make(handler)
    with pytest.raises(SourceUnavailable):
        client.company_identify({"domains": ["x.com"]})
    assert len(calls) == 4
    assert time.sleeps == [1.0, 2.0, 4.0]
    assert recorder.calls == []


def test_timeout_is_retried_then_succeeds() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectTimeout("slow", request=request)
        return replay("crustdata/company_identify")

    client, _, time = make(handler)
    assert client.company_identify({"domains": ["lumenledger.io"]}).credits == 0.2
    assert time.sleeps == [1.0]


@pytest.mark.parametrize(
    ("status", "error"),
    [(402, CreditsExhausted), (401, CrustdataAuthError), (403, CrustdataAuthError),
     (400, CrustdataBadRequest)],
)
def test_client_errors_raise_without_retry(status: int, error: type[Exception]) -> None:
    calls: list[int] = []
    body = {"error": {"type": "insufficient_credits", "message": "no", "metadata": []}}

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status, json=body)

    client, _, _ = make(handler)
    with pytest.raises(error) as info:
        client.company_search({})
    assert len(calls) == 1
    if isinstance(info.value, CrustdataBadRequest):
        assert info.value.body == body


def test_cache_hit_spends_nothing() -> None:
    calls: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return replay("crustdata/person_enrich")

    client, recorder, _ = make(handler)
    body = fixture("crustdata/person_enrich")["request"]
    first = client.person_enrich(body)
    second = client.person_enrich(dict(reversed(body.items())))

    assert len(calls) == 1
    assert second.cached and second.credits == 0 and second.data == first.data
    assert second.source_id == first.source_id
    assert [(c.cached, c.units) for c in recorder.calls] == [(False, 1.0), (True, 0.0)]


def test_stale_cache_is_refetched() -> None:
    now = datetime(2026, 11, 22, tzinfo=UTC)
    recorder = InMemoryRecorder(now=lambda: now)
    calls: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return replay("crustdata/company_autocomplete")

    client, _, _ = make(handler, recorder)
    client.company_autocomplete({"field": "x", "query": "y"})
    now += timedelta(hours=25)
    assert not client.company_autocomplete({"field": "x", "query": "y"}).cached
    assert len(calls) == 2


def test_request_hash_ignores_key_order() -> None:
    a = {"filters": {"field": "f", "type": "=", "value": 1}, "limit": 5}
    b = {"limit": 5, "filters": {"value": 1, "type": "=", "field": "f"}}
    assert request_hash("/person/search", a) == request_hash("/person/search", b)
    assert request_hash("/person/search", a) != request_hash("/company/search", a)


def test_rate_limiter_delays_6th_search_call_in_a_minute() -> None:
    client, _, time = make(lambda _: replay("crustdata/company_search"))
    for i in range(5):
        client.company_search({"page": i})
    assert time.sleeps == []

    client.company_search({"page": 5})
    assert time.sleeps == [60.0]


def test_enrich_limit_is_5_per_minute() -> None:
    client, _, time = make(lambda _: replay("crustdata/company_enrich"))
    for i in range(6):
        client.company_enrich({"crustdata_company_ids": [i]})
    assert time.sleeps == [60.0]


def test_autocomplete_is_not_held_to_the_search_limit() -> None:
    client, _, time = make(lambda _: replay("crustdata/company_autocomplete"))
    for i in range(30):
        client.company_autocomplete({"field": "x", "query": f"q{i}"})
    assert time.sleeps == []


def test_endpoint_paths_and_watch_calls() -> None:
    paths: list[tuple[str, str]] = []
    by_path = {fixture(f"crustdata/{n}")["endpoint"]: n for n in (
        "company_autocomplete", "person_autocomplete", "social_post_search",
        "watch_company_create", "watch_test_notification", "watch_runs", "account_credits")}

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        return replay(f"crustdata/{by_path[request.url.path]}")

    client, recorder, _ = make(handler)
    client.company_autocomplete({"field": "basic_info.industries", "query": "tech"})
    client.person_autocomplete({"field": "x", "query": "VP"})
    client.social_post_search({"limit": 1})
    watch = client.watch_company_create(fixture("crustdata/watch_company_create")["request"])
    client.watch_test_notification(watch.data["id"], {})
    client.watch_runs(watch.data["id"], limit=10)
    balance = client.credits_balance()

    assert balance.data["account"]["credits"] == 9406.5
    assert paths == [
        ("POST", "/company/search/autocomplete"), ("POST", "/person/search/autocomplete"),
        ("POST", "/social_post/search"), ("POST", "/watch/company"),
        ("POST", "/watch/company/46936/test"), ("GET", "/watch/company/46936/runs"),
        ("GET", "/account/credits"),
    ]
    assert [c.units for c in recorder.calls] == [0, 0, 0.5, 0, 0, 0, 0]
