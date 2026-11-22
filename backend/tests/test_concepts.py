import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.llm import FakeLLM
from app.models.entities import Company
from app.models.enums import SourceKind
from app.models.evidence import Fact, Source
from app.services.clients import clients_for_run
from app.services.search import concepts
from app.services.search.concepts import CONCEPT_MATCH, record_fits, rerank

PIXXEL = "Pixxel builds hyperspectral imaging satellites for earth observation."
M2P = "M2P powers lending and card issuing for banks."
AGNIKUL = "Agnikul makes 3D-printed rocket engines and small launch vehicles."


def cand(cid: int, name: str, description: str | None) -> dict[str, Any]:
    row: dict[str, Any] = {"crustdata_company_id": cid, "found_by": ["company"], "name": name}
    if description:
        row.update(description=description, source_id=str(uuid.uuid4()),
                   path=f"companies[{cid}].basic_info.description")
    return row


def run(llm: FakeLLM, candidates: list[dict[str, Any]], concept_list: list[str],
        ranking: str | None = None) -> dict[str, Any]:
    clients = clients_for_run(None, transport=httpx.MockTransport(lambda r: httpx.Response(500)),
                              llm_transport=llm)
    return rerank(clients, candidates, concept_list, ranking, lambda: None)


def ids(rows: list[dict[str, Any]]) -> list[int]:
    return [r["crustdata_company_id"] for r in rows]


def test_hard_concept_keeps_good_fits_best_first_and_excludes_the_rest() -> None:
    llm = FakeLLM({"ratings": [
        {"index": 0, "fit": 0, "quote": "", "reason": "financial software"},
        {"index": 1, "fit": 2, "quote": "3D-printed rocket engines", "reason": "space hardware"},
        {"index": 2, "fit": 3, "quote": "hyperspectral imaging satellites", "reason": "core"},
    ]})
    out = run(llm, [cand(1, "M2P", M2P), cand(2, "Agnikul", AGNIKUL), cand(3, "Pixxel", PIXXEL)],
              ["deeptech"])
    assert out["hard"] is True
    assert ids(out["kept"]) == [3, 2]  # fit 3 before fit 2, though found later
    assert out["kept"][0]["quote"] == "hyperspectral imaging satellites"
    assert out["excluded"] == [{"crustdata_company_id": 1, "name": "M2P", "fit": 0,
                                "reason": "financial software"}]
    # one batched call on the fast model, before any enrichment
    [request] = llm.requests
    assert request["model"] == "anthropic/claude-haiku-5.5"
    assert "Must be: deeptech." in request["messages"][-1]["content"]


def test_a_quote_not_in_the_description_counts_as_no_fit() -> None:
    llm = FakeLLM({"ratings": [
        {"index": 0, "fit": 3, "quote": "quantum computing chips", "reason": "deeptech"}]})
    out = run(llm, [cand(1, "Acme", "Acme sells cosmetics online.")], ["deeptech"])
    assert out["kept"] == []
    assert "not supported" in out["excluded"][0]["reason"]


def test_no_description_is_excluded_under_a_concept_without_calling_the_llm() -> None:
    llm = FakeLLM()
    out = run(llm, [cand(1, "Blank", None)], ["deeptech"])
    assert out["kept"] == [] and llm.requests == []
    assert out["excluded"][0]["reason"] == "no company description to check the concept against"


def test_ranking_description_only_reorders_it_never_excludes() -> None:
    llm = FakeLLM({"ratings": [
        {"index": 0, "fit": 0, "quote": "", "reason": "banking software"},
        {"index": 1, "fit": 3, "quote": "rocket engines", "reason": "launch"},
    ]})
    out = run(llm, [cand(1, "M2P", M2P), cand(2, "Agnikul", AGNIKUL), cand(3, "Blank", None)],
              [], ranking="Indian space-tech hardware startups")
    assert out["hard"] is False and out["excluded"] == []
    # rated fit first, unrated (no description) in the middle, zero fit last
    assert ids(out["kept"]) == [2, 3, 1]


def test_min_fit_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "search_concept_min_fit", 3)
    llm = FakeLLM({"ratings": [
        {"index": 0, "fit": 2, "quote": "rocket engines", "reason": "adjacent"}]})
    out = run(llm, [cand(1, "Agnikul", AGNIKUL)], ["deeptech"])
    assert out["kept"] == []


def test_large_pools_are_rated_in_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(concepts, "BATCH", 2)
    llm = FakeLLM(
        {"ratings": [{"index": 0, "fit": 1, "quote": "rocket", "reason": "r"},
                     {"index": 1, "fit": 3, "quote": "satellites", "reason": "r"}]},
        {"ratings": [{"index": 0, "fit": 2, "quote": "lending", "reason": "r"}]},
    )
    out = run(llm, [cand(1, "Agnikul", AGNIKUL), cand(2, "Pixxel", PIXXEL), cand(3, "M2P", M2P)],
              [], ranking="anything")
    assert len(llm.requests) == 2
    assert ids(out["kept"]) == [2, 3, 1]


def test_record_fits_cites_the_search_row_and_is_idempotent(db: Session) -> None:
    source = Source(kind=SourceKind.crustdata, endpoint_or_url="/company/search")
    company = Company(crustdata_company_id=3, name="Pixxel")
    db.add_all([source, company])
    db.flush()
    row = {**cand(3, "Pixxel", PIXXEL), "source_id": str(source.id), "fit": 3,
           "quote": "hyperspectral imaging satellites", "reason": "core"}
    unrated = {**cand(4, "Other", None), "fit": None, "quote": "", "reason": None}
    companies = {"3": str(company.id), "4": str(uuid.uuid4())}

    assert record_fits(db, [row, unrated], companies) == 1
    assert record_fits(db, [row, unrated], companies) == 0
    db.commit()
    [fact] = db.scalars(select(Fact).where(Fact.predicate == CONCEPT_MATCH)).all()
    assert fact.subject_id == company.id and fact.source_id == source.id
    assert fact.value == {"fit": 3, "quote": "hyperspectral imaging satellites",
                          "reason": "core"}
    assert fact.locator == {"path": "companies[3].basic_info.description",
                            "quote": "hyperspectral imaging satellites"}
