import json

import httpx
import pytest

from app.integrations.errors import SourceUnavailable
from app.integrations.recorder import InMemoryRecorder
from app.integrations.web import WebClient
from tests.test_integrations_crustdata import FakeSettings, FakeTime, Handler, fixture, replay


def make(handler: Handler) -> tuple[WebClient, InMemoryRecorder, FakeTime]:
    recorder, time = InMemoryRecorder(), FakeTime()
    client = WebClient(FakeSettings(), recorder, transport=httpx.MockTransport(handler),
                       clock=time.clock, sleep=time.sleep, jitter=lambda: 0.0)
    return client, recorder, time


def test_search_builds_body_and_records_web_kind() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/web/search/live"
        bodies.append(json.loads(request.content))
        return replay("web/search")

    client, recorder, _ = make(handler)
    result = client.search("Lumen Ledger funding", site="example.com", start_date=1728259200)

    assert bodies == [{"query": "Lumen Ledger funding", "page": 1, "site": "example.com",
                       "start_date": 1728259200}]
    assert result.data["results"][0]["url"] == "https://example.com/lumen-ledger-120m"
    [call] = recorder.calls
    assert call.provider == "web" and call.kind == "web" and call.units == 1.0


def test_news_search_records_news_kind() -> None:
    client, recorder, _ = make(lambda _: replay("web/search_news"))
    client.search("Lumen Ledger", sources=["news"])
    assert recorder.calls[0].kind == "news"


def test_fetch_records_url_and_estimates_when_header_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/web/enrich/live"
        return httpx.Response(200, json=fixture("web/fetch")["response"])

    client, recorder, _ = make(handler)
    url = "https://example.com/lumen-ledger-120m"
    result = client.fetch(url)

    assert result.data[0]["title"].startswith("Lumen Ledger")
    assert result.credits == 1.0 and result.credits_estimated
    assert recorder.calls[0].url == url


def test_web_limit_is_10_per_minute() -> None:
    client, _, time = make(lambda _: replay("web/search"))
    for i in range(11):
        client.search(f"q{i}")
    assert time.sleeps == [60.0]


def test_web_shares_retry_behaviour() -> None:
    client, _, time = make(lambda _: httpx.Response(500))
    with pytest.raises(SourceUnavailable):
        client.fetch("https://example.com")
    assert time.sleeps == [1.0, 2.0, 4.0]
