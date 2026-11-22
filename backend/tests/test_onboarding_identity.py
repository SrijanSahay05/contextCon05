import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.identity import Fund, Investor
from app.models.runs import Job, Run
from app.services import clients
from app.services.onboarding import identity, identity_job

FIXTURES = Path(__file__).parent / "fixtures" / "crustdata"
LINKEDIN = "https://www.linkedin.com/in/ananya-rao-accel"


def _key(path: str, body: Any) -> str:
    return f"{path} {json.dumps(body, sort_keys=True)}"


class FakeCrust:
    """Replays fixtures whose recorded request equals the outgoing one; else 400."""

    def __init__(self, *names: str) -> None:
        self.routes: dict[str, dict[str, Any]] = {}
        for name in names:
            fx = json.loads((FIXTURES / f"{name}.json").read_text())
            self.routes[_key(fx["endpoint"], fx["request"])] = fx
        self.seen: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        key = _key(request.url.path, json.loads(request.content))
        self.seen.append(key)
        fx = self.routes.get(key)
        if fx is None:
            return httpx.Response(400, json={"error": f"unexpected request {key}"})
        return httpx.Response(200, json=fx["response"], headers=fx["headers"])


ALL = (
    "person_enrich_partner", "company_identify_accel", "person_search_namesakes",
    "company_enrich_accel_profile", "company_search_accel", "company_enrich_accel_portfolio",
)


@pytest.fixture
def crust(monkeypatch: pytest.MonkeyPatch) -> FakeCrust:
    fake = FakeCrust(*ALL)
    transport = httpx.MockTransport(fake)

    def patched(run_id: Any) -> clients.Clients:
        return clients.clients_for_run(run_id, transport=transport)

    monkeypatch.setattr(identity, "clients_for_run", patched)
    monkeypatch.setattr(identity_job, "clients_for_run", patched)
    return fake


def _headers(investor_id: str) -> dict[str, str]:
    return {"X-Investor-Id": investor_id}


def onboard_and_confirm(client: TestClient, person_id: int = 990001) -> tuple[str, dict[str, Any]]:
    res = client.post("/investors/onboard", json={"linkedin_url": LINKEDIN})
    assert res.status_code == 201, res.text
    investor_id = res.json()["investor_id"]
    res = client.post(f"/investors/{investor_id}/confirm-identity",
                      json={"crustdata_person_id": person_id}, headers=_headers(investor_id))
    assert res.status_code == 202, res.text
    return investor_id, res.json()


def test_linkedin_onboarding_returns_one_candidate(client: TestClient, crust: FakeCrust) -> None:
    res = client.post("/investors/onboard", json={"linkedin_url": LINKEDIN})
    assert res.status_code == 201, res.text
    body = res.json()
    assert [c["crustdata_person_id"] for c in body["candidates"]] == [990001]
    cand = body["candidates"][0]
    assert cand["current_company"] == "Accel" and cand["linkedin_url"] == LINKEDIN
    assert cand["location"] == "Bengaluru, India"

    res = client.get(f"/investors/{body['investor_id']}", headers=_headers(body["investor_id"]))
    assert res.status_code == 200
    assert res.json()["onboarding_step"] == "confirm_identity"


def test_name_and_firm_with_namesakes_returns_both(client: TestClient, crust: FakeCrust) -> None:
    res = client.post("/investors/onboard", json={"name": "Ananya Rao", "firm": "Accel"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert {c["crustdata_person_id"] for c in body["candidates"]} == {990001, 990002}
    res = client.get(f"/investors/{body['investor_id']}", headers=_headers(body["investor_id"]))
    assert res.json()["identity_confirmed_at"] is None  # never auto-picked


def test_unresolved_linkedin_returns_no_candidates(client: TestClient, crust: FakeCrust) -> None:
    res = client.post("/investors/onboard", json={"linkedin_url": "https://linkedin.com/in/nobody"})
    assert res.status_code == 201
    assert res.json()["candidates"] == []


def test_confirm_with_non_candidate_is_rejected(client: TestClient, crust: FakeCrust) -> None:
    investor_id = client.post("/investors/onboard", json={"linkedin_url": LINKEDIN}).json()[
        "investor_id"]
    res = client.post(f"/investors/{investor_id}/confirm-identity",
                      json={"crustdata_person_id": 12345}, headers=_headers(investor_id))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


def test_confirm_unknown_investor_is_404(client: TestClient) -> None:
    missing = "00000000-0000-4000-8000-000000000000"
    res = client.post(f"/investors/{missing}/confirm-identity",
                      json={"crustdata_person_id": 1}, headers=_headers(missing))
    assert res.status_code == 404


def test_confirm_creates_fund_and_enqueues_once(
    client: TestClient, crust: FakeCrust, db: Session
) -> None:
    investor_id, accepted = onboard_and_confirm(client)
    assert accepted["status_url"] == f"/runs/{accepted['run_id']}"

    investor = db.get(Investor, UUID(investor_id))
    assert investor and investor.crustdata_person_id == 990001
    assert investor.identity_confirmed_at is not None and investor.title == "Partner"
    assert investor.linkedin_url == LINKEDIN
    fund = db.get(Fund, investor.fund_id)
    assert fund and fund.crustdata_company_id == 500100 and fund.name == "Accel"

    job = db.scalar(select(Job).where(Job.kind == "onboarding_identity"))
    assert job and str(job.run_id) == accepted["run_id"]
    assert job.payload["fund_id"] == str(fund.id) and job.payload["recent_move"] is False

    again = client.post(f"/investors/{investor_id}/confirm-identity",
                        json={"crustdata_person_id": 990001}, headers=_headers(investor_id))
    assert again.status_code == 202 and again.json()["run_id"] == accepted["run_id"]
    assert db.scalar(select(func.count()).select_from(Job)) == 1
    assert db.scalar(select(func.count()).select_from(Run)) == 1

    out = client.get(f"/investors/{investor_id}", headers=_headers(investor_id)).json()
    assert out["onboarding_step"] == "confirm_aliases"
    assert out["onboarding_run_id"] == accepted["run_id"]
    assert out["fund"]["crustdata_company_id"] == 500100


def test_upstream_failures_use_the_envelope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(402, json={"error": "no credits"}))
    monkeypatch.setattr(identity, "clients_for_run",
                        lambda run_id: clients.clients_for_run(run_id, transport=transport))
    res = client.post("/investors/onboard", json={"name": "Ananya Rao", "firm": "Accel"})
    assert res.status_code == 402
    assert res.json()["error"]["code"] == "credits_exhausted"
