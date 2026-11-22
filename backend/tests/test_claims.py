from typing import Any

import pytest

from app.integrations.llm import FakeLLM
from app.services import clients
from app.services.dd.claims import extract_claims, to_number

PAGES = [
    "Ledgerline (team-made test text)\nA team of 40 engineers   across Pune",
    "We raised $4.5M in our seed round led by Kestrel Ventures.",
]


def _claim(**over: Any) -> dict[str, Any]:
    return {"predicate": "headcount_total", "value": "40 engineers", "as_of": "2026-09",
            "page": 1, "quote": "A team of 40 engineers across Pune", **over}


def _extract(*claims: dict[str, Any]) -> list[Any]:
    llm = FakeLLM({"claims": list(claims)})
    return extract_claims(clients.clients_for_run(None, llm_transport=llm), PAGES)


@pytest.mark.parametrize(("raw", "expected"), [
    ("40 engineers", 40), ("$4.5M", 4500000), ("1,200 customers", 1200), (2019, 2019),
    ("$300k ARR", 300000), ("USD 2 million", 2000000), ("40 members", 40), ("none", None),
])
def test_to_number(raw: Any, expected: Any) -> None:
    assert to_number(raw) == expected


def test_quote_on_its_page_is_kept_and_normalised() -> None:
    [claim] = _extract(_claim())  # whitespace differs from the page: still found
    assert (claim.predicate, claim.value, claim.page) == ("headcount_total", 40, 1)
    assert claim.as_of is not None and claim.as_of.isoformat() == "2026-09-01"


def test_round_amount_is_normalised() -> None:
    [claim] = _extract(_claim(predicate="funding_round", page=2,
                              value={"round_type": "seed", "amount_usd": "$4.5M"},
                              quote="We raised $4.5M in our seed round"))
    assert claim.value == {"round_type": "seed", "amount_usd": 4500000}


def test_quote_not_on_the_page_is_dropped() -> None:
    assert _extract(_claim(page=2), _claim(quote="A team of 60 engineers")) == []


def test_unknown_predicate_or_unparseable_number_is_dropped() -> None:
    assert _extract(_claim(predicate="market_size_usd", value="$10B"),
                    _claim(value="a big team")) == []


def test_one_call_for_small_pages_and_none_for_empty_ones() -> None:
    llm = FakeLLM({"claims": []})
    extract_claims(clients.clients_for_run(None, llm_transport=llm), PAGES + ["", "  "])
    assert len(llm.requests) == 1
    assert "--- page 2 ---" in llm.requests[0]["messages"][1]["content"]
