import uuid
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.llm import FakeLLM
from app.models.entities import Company
from app.models.enums import CandidateStatus, ReviewStatus
from app.models.identity import Fund, Investor
from app.models.onboarding import Thesis
from app.models.runs import Job, Run
from app.models.search import Candidate, Search
from app.services import clients
from app.services.search import searches
from tests.test_query_parser import BITS_QUERY, BITS_REPLY, FakeAutocomplete


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    fake = FakeLLM()
    transport = httpx.MockTransport(FakeAutocomplete())

    def patched(run_id: Any) -> clients.Clients:
        return clients.clients_for_run(run_id, transport=transport, llm_transport=fake)

    monkeypatch.setattr(searches, "clients_for_run", patched)
    return fake


def investor(db: Session) -> dict[str, str]:
    fund = Fund(name="Kestrel")
    db.add(fund)
    db.flush()
    inv = Investor(name="P", fund_id=fund.id)
    db.add(inv)
    db.commit()
    return {"X-Investor-Id": str(inv.id)}


def test_create_edit_run(client: TestClient, db: Session, llm: FakeLLM) -> None:
    h = investor(db)
    llm.queue(BITS_REPLY)
    res = client.post("/searches", json={"query": BITS_QUERY, "as_of": "2026-11-22"},
                      headers=h)
    assert res.status_code == 201
    created = res.json()
    assert created["status"] == "draft" and created["unresolved"] == []
    assert created["parsed_filters"]["window_months"] == 6
    assert created["thesis_id"] is None and created["candidates"] == []
    sid = created["id"]

    filters = created["parsed_filters"] | {"window_months": 12}
    edited = client.put(f"/searches/{sid}/filters", json=filters, headers=h).json()
    assert edited["parsed_filters"]["window_months"] == 12 and edited["status"] == "draft"

    first = client.post(f"/searches/{sid}/run", headers=h)
    assert first.status_code == 202
    again = client.post(f"/searches/{sid}/run", headers=h)
    assert again.json()["run_id"] == first.json()["run_id"]
    run_id = uuid.UUID(first.json()["run_id"])
    run = db.get(Run, run_id)
    assert run is not None and run.kind == "search"
    assert run.subject == {"search_id": sid, "investor_id": h["X-Investor-Id"]}
    jobs = db.scalars(select(Job).where(Job.kind == "search_run")).all()
    assert [(j.idempotency_key, j.run_id) for j in jobs] == [(f"search_run:{sid}", run_id)]
    got = client.get(f"/searches/{sid}", headers=h).json()
    assert got["status"] == "running" and got["run_id"] == str(run_id)

    res = client.put(f"/searches/{sid}/filters", json=filters, headers=h)
    assert res.status_code == 409 and res.json()["error"]["code"] == "conflict"


def test_run_with_unresolved_is_409(client: TestClient, db: Session, llm: FakeLLM) -> None:
    h = investor(db)
    llm.queue({"schools": [{"phrase": "Xyzzy College"}]})
    created = client.post("/searches", json={"query": "founders from Xyzzy College"},
                          headers=h).json()
    assert created["unresolved"] == [{"term": "Xyzzy College", "suggestions": []}]

    res = client.post(f"/searches/{created['id']}/run", headers=h)
    assert res.status_code == 409
    assert res.json()["error"]["details"]["unresolved"][0]["term"] == "Xyzzy College"
    assert db.scalar(select(func.count()).select_from(Job)) == 0

    # editing the chips settles the unresolved terms
    client.put(f"/searches/{created['id']}/filters", json=created["parsed_filters"],
               headers=h)
    assert client.post(f"/searches/{created['id']}/run", headers=h).status_code == 202


def test_attaches_latest_confirmed_thesis(client: TestClient, db: Session,
                                          llm: FakeLLM) -> None:
    h = investor(db)
    inv = db.get(Investor, uuid.UUID(h["X-Investor-Id"]))
    assert inv is not None and inv.fund_id is not None
    ids = []
    for version, status in ((1, ReviewStatus.confirmed), (2, ReviewStatus.draft)):
        thesis = Thesis(investor_id=inv.id, fund_id=inv.fund_id, version=version,
                        status=status, confidence="low", points=[])
        db.add(thesis)
        db.flush()
        ids.append(str(thesis.id))
    db.commit()
    llm.queue({})
    created = client.post("/searches", json={"query": "anything good"}, headers=h).json()
    assert created["thesis_id"] == ids[0] and created["profile_id"] is None


def test_upstream_failure_maps_to_503(client: TestClient, db: Session, llm: FakeLLM) -> None:
    h = investor(db)
    llm.queue("no tool call", "still none")
    res = client.post("/searches", json={"query": "fintech in India"}, headers=h)
    assert res.status_code == 503 and res.json()["error"]["code"] == "upstream_unavailable"
    assert db.scalar(select(func.count()).select_from(Search)) == 0


def test_list_and_get_scoped_and_sorted(client: TestClient, db: Session) -> None:
    h, other = investor(db), investor(db)
    search = Search(investor_id=uuid.UUID(h["X-Investor-Id"]), query_text="q",
                    parsed_filters={}, unresolved=[])
    db.add(search)
    db.flush()
    for n, score in enumerate((None, 40.5, 81.0)):
        company = Company(crustdata_company_id=n + 1, name=f"Co{n}", domain=f"co{n}.in")
        db.add(company)
        db.flush()
        db.add(Candidate(search_id=search.id, company_id=company.id, score=score,
                         completeness=0.5 if score else None, breakdown=[],
                         status=CandidateStatus.new))
    db.commit()

    got = client.get(f"/searches/{search.id}", headers=h).json()
    assert [c["score"] for c in got["candidates"]] == [81.0, 40.5, None]
    assert got["candidates"][0]["company_name"] == "Co2"

    listed = client.get("/searches", headers=h).json()
    assert listed["total"] == 1 and listed["items"][0]["candidates"] == []
    assert client.get("/searches", headers=other).json() == {"items": [], "total": 0}
    for method, path in (("get", ""), ("put", "/filters"), ("post", "/run")):
        res = client.request(method, f"/searches/{search.id}{path}", headers=other,
                             json={} if method == "put" else None)
        assert res.status_code == 404, path
