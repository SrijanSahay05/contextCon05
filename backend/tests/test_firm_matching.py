from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import Fund, FundAlias
from app.models.runs import Job, RunStep
from app.services.onboarding import firm
from app.worker import run_once
from tests.test_onboarding_identity import FakeCrust, _headers, crust, onboard_and_confirm

__all__ = ["crust"]  # pytest fixture re-used from the identity tests


def test_is_close_matches_whole_words_only() -> None:
    assert firm.is_close("Accel-KKR", ["Accel"])
    assert firm.is_close("Accel India", ["Accel"])
    assert firm.is_close("accel  (lead)", ["Accel"])
    assert not firm.is_close("Acceleration Partners", ["Accel"])


def test_preselected_needs_exactly_one_exact_match() -> None:
    enriched = [({"basic_info": {"name": "Co"}, "funding": {"investors_detailed": [
        {"name": "Kestrel Ventures", "permalink": "kestrel-ventures"},
        {"name": "Kestrel Ventures", "permalink": "kestrel-ventures-2"},
    ]}}, "00000000-0000-4000-8000-000000000001")]
    groups = firm.group_candidates(enriched, [], ["Kestrel Ventures", "kestrel"],
                                   "Kestrel Ventures")
    assert len(groups) == 2 and not any(g["preselected"] for g in groups)


def _run_identity_job(client: TestClient, db: Session) -> tuple[str, str]:
    investor_id, accepted = onboard_and_confirm(client)
    fund_id = client.get(f"/investors/{investor_id}", headers=_headers(investor_id)).json()[
        "fund"]["id"]
    res = client.get(f"/funds/{fund_id}/alias-candidates", headers=_headers(investor_id))
    assert res.status_code == 409 and res.json()["error"]["code"] == "conflict"
    assert run_once(db, "test-worker")
    step = db.get(RunStep, (UUID(accepted["run_id"]), "alias_candidates"))
    assert step is not None and step.status == "done"
    return investor_id, fund_id


def test_alias_candidates_group_lookalikes_by_permalink(
    client: TestClient, crust: FakeCrust, db: Session
) -> None:
    investor_id, fund_id = _run_identity_job(client, db)
    fund = db.get(Fund, UUID(fund_id))
    assert fund and fund.domain == "accel.com"

    res = client.get(f"/funds/{fund_id}/alias-candidates", headers=_headers(investor_id))
    assert res.status_code == 200, res.text
    groups = {g["permalink"]: g for g in res.json()}
    assert set(groups) == {"accel", "accel-kkr", "accel-india"}  # not acceleration-partners
    assert groups["accel"]["example_companies"] == ["Lumen Ledger", "Paysetu", "Kirana Cloud"]
    assert groups["accel"]["deal_count"] == 4
    assert groups["accel-kkr"]["example_companies"] == ["Lumen Ledger", "Agrovia"]
    assert [p for p, g in groups.items() if g["preselected"]] == ["accel"]

    out = client.get(f"/investors/{investor_id}", headers=_headers(investor_id)).json()
    assert out["onboarding_step"] == "confirm_aliases"


def test_confirm_aliases_stores_them_and_enqueues_thesis(
    client: TestClient, crust: FakeCrust, db: Session
) -> None:
    investor_id, fund_id = _run_identity_job(client, db)

    bad = client.post(f"/funds/{fund_id}/aliases", json={"permalinks": ["accel", "nope"]},
                      headers=_headers(investor_id))
    assert bad.status_code == 422 and bad.json()["error"]["details"]["permalinks"] == ["nope"]

    res = client.post(f"/funds/{fund_id}/aliases", json={"permalinks": ["accel-india", "accel"]},
                      headers=_headers(investor_id))
    assert res.status_code == 202, res.text
    aliases = db.scalars(select(FundAlias).where(FundAlias.fund_id == UUID(fund_id))).all()
    assert {(a.permalink, a.canonical_name) for a in aliases} == {
        ("accel", "Accel"), ("accel-india", "Accel India")}
    assert all(str(a.confirmed_by) == investor_id and a.source_id for a in aliases)

    job = db.scalar(select(Job).where(Job.kind == "onboarding_thesis"))
    assert job and str(job.run_id) == res.json()["run_id"]
    assert job.idempotency_key == f"onboarding_thesis:{fund_id}:accel,accel-india"
    assert job.payload == {"investor_id": investor_id, "fund_id": fund_id}

    out = client.get(f"/investors/{investor_id}", headers=_headers(investor_id)).json()
    assert out["onboarding_step"] == "building_thesis"
    assert out["onboarding_run_id"] == res.json()["run_id"]


def test_alias_routes_unknown_fund_is_404(client: TestClient) -> None:
    missing = "00000000-0000-4000-8000-000000000000"
    res = client.get(f"/funds/{missing}/alias-candidates", headers=_headers(missing))
    assert res.status_code == 404
