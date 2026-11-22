import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from app.integrations.llm import FakeLLM
from app.services.clients import Clients, clients_for_run
from app.services.search.query_parser import months_before, parse_query

FIXTURE = Path(__file__).parent / "fixtures" / "search" / "autocomplete.json"


class FakeAutocomplete:
    """Replays the fixture's autocomplete replies; anything else gets no suggestions."""

    def __init__(self) -> None:
        replies = json.loads(FIXTURE.read_text())["replies"]
        self.routes = {_key(r["endpoint"], r["request"]): r["response"] for r in replies}
        self.seen: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.seen.append(body)
        reply = self.routes.get(_key(request.url.path, body), {"suggestions": []})
        return httpx.Response(200, json=reply, headers={"x-credits-used": "0"})


def _key(path: str, body: Any) -> str:
    return f"{path} {json.dumps(body, sort_keys=True)}"


def make_clients(llm: FakeLLM, crust: FakeAutocomplete) -> Clients:
    return clients_for_run(None, transport=httpx.MockTransport(crust), llm_transport=llm)


BITS_QUERY = (
    "BITSian startups building in deeptech that got government grants in the last 6 months"
)
BITS_REPLY = {
    "schools": [{"phrase": "BITSian"}],
    "concepts": [{"phrase": "deeptech"}],
    "funding_window": {"phrase": "in the last 6 months", "months": 6},
    "grants": {"required": True, "programs": []},
}


def test_bits_deeptech_grants_query() -> None:
    crust = FakeAutocomplete()
    spec, unresolved = parse_query(
        make_clients(FakeLLM(BITS_REPLY), crust), BITS_QUERY, None, as_of=date(2026, 11, 22)
    )
    assert unresolved == []
    # every BITS spelling is looked up; matches are combined, a different school is not
    assert [b["query"] for b in crust.seen] == [
        "Birla Institute of Technology and Science", "Birla Institute of Technology & Science",
        "BITS Pilani", "BITS, Pilani", "BITS-Pilani",
    ]
    [school] = spec.people
    assert school.field == "education.schools.school" and school.op == "in"
    assert school.value == [
        "Birla Institute of Technology and Science, Pilani",
        "Birla Institute of Technology and Science, Pilani - Goa Campus",
        "Birla Institute of Technology & Science, Pilani",
        # alias spellings keep every campus variant, not just the exact match
        # ("BITS-PILANI" comes from its own "BITS-Pilani" lookup, not listed in the fixture)
        "BITS Pilani, Hyderabad Campus", "BITS Pilani", "BITS Pilani Dubai",
    ]
    assert "Birla Institute of Technology, Mesra" not in school.value
    [concept] = spec.companies
    assert (concept.op, concept.value) == ("semantic", "deeptech")
    [window] = spec.funding
    assert (window.field, window.op, window.value) == (
        "funding.last_fundraise_date", ">", "2026-05-22")
    assert spec.window_months == 6
    assert spec.grants is not None and spec.grants.required


def test_unknown_school_is_unresolved_not_guessed() -> None:
    reply = {"schools": [{"phrase": "Hogwarts Poly"}, {"phrase": "Xyzzy College"}],
             "hq_countries": [{"phrase": "India"}]}
    spec, unresolved = parse_query(
        make_clients(FakeLLM(reply), FakeAutocomplete()),
        "founders from Hogwarts Poly or Xyzzy College, based in India", None,
    )
    assert spec.people == []
    assert [u.model_dump() for u in unresolved] == [
        {"term": "Hogwarts Poly", "suggestions": ["Hogwarts University"]},
        {"term": "Xyzzy College", "suggestions": []},
    ]
    [country] = spec.companies
    assert (country.field, country.value) == ("locations.country", ["India"])


def test_invented_values_are_dropped() -> None:
    reply = {
        "schools": [{"phrase": "IIT Bombay"}],
        "concepts": [{"phrase": "deeptech"}, {"phrase": "quantum computing"}],
        "funding_window": {"phrase": "last 18 months", "months": 18},
        "grants": {"required": True, "programs": ["BIRAC BIG"]},
    }
    crust = FakeAutocomplete()
    spec, unresolved = parse_query(
        make_clients(FakeLLM(reply), crust), BITS_QUERY, None, as_of=date(2026, 11, 22)
    )
    assert crust.seen == [] and unresolved == [] and spec.people == []
    assert [c.value for c in spec.companies] == ["deeptech"]
    assert spec.funding == [] and spec.window_months is None
    assert spec.grants is not None and spec.grants.programs == []


def test_months_before_clamps_day() -> None:
    assert months_before(date(2026, 8, 31), 6) == date(2026, 2, 28)
    assert months_before(date(2026, 3, 15), 18) == date(2024, 9, 15)
