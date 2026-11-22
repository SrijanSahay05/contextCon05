import uuid
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.entities import Company
from app.models.enums import Confidence, ProfileOrigin, SourceKind
from app.models.evidence import Source
from app.models.identity import Fund, Investor
from app.models.onboarding import Deal
from app.repositories import profiles, theses
from app.schemas.profile import EX_CRITERIA, EX_THRESHOLDS, EX_TIERS


def seed(db: Session) -> tuple[Investor, uuid.UUID, uuid.UUID, uuid.UUID]:
    fund = Fund(name="Kestrel")
    db.add(fund)
    db.flush()
    investor = Investor(name="P", fund_id=fund.id)
    company = Company(crustdata_company_id=1, name="Paysetu", domain="paysetu.in")
    source = Source(kind=SourceKind.crustdata, endpoint_or_url="/company/enrich")
    db.add_all([investor, company, source])
    db.flush()
    deal = Deal(fund_id=fund.id, company_id=company.id, round_date=date(2026, 3, 1),
                round_type="seed", amount_usd=2e6, led=True, match_rule="exact_round_name",
                match_evidence={}, source_id=source.id)
    db.add(deal)
    db.flush()
    thesis = theses.create(
        db, investor_id=investor.id, fund_id=fund.id,
        window=(date(2025, 5, 1), date(2026, 11, 1)), confidence=Confidence.low,
        points=[{"dimension": "stage", "statement": "100% seed", "value": {"seed": 1.0},
                 "deal_ids": [str(deal.id)]}],
        summary="100% seed.",
    )
    profile = profiles.create(
        db, investor_id=investor.id, thesis_id=thesis.id, origin=ProfileOrigin.generic,
        confidence=Confidence.low, criteria=EX_CRITERIA, thresholds=EX_THRESHOLDS,
        self_reported_weight=0.5, source_tiers=EX_TIERS,
        derivation=[{"target": "profile", "change": "generic weights", "reason": "few deals",
                     "evidence_ids": [str(deal.id)]}],
    )
    db.commit()
    return investor, thesis.id, profile.id, deal.id


def test_thesis_get_edit_confirm(client: TestClient, db: Session) -> None:
    investor, thesis_id, _, deal_id = seed(db)
    h = {"X-Investor-Id": str(investor.id)}

    got = client.get(f"/theses/{thesis_id}", headers=h).json()
    assert got["deal_count"] == 1 and got["deals"][0]["company_name"] == "Paysetu"
    assert client.get(f"/theses/{thesis_id}", headers={"X-Investor-Id": str(uuid.uuid4())}
                      ).status_code == 404

    edit = {
        "points": [got["points"][0], {"dimension": "exclusion", "statement": "No crypto",
                                      "value": "crypto", "deal_ids": []}],
        "added_deals": [{"company_name": "Kirana Cloud", "url": "https://news.example/k",
                         "round_type": "seed", "round_date": "2025-08-02"}],
        "removed_deal_ids": [str(deal_id)],
    }
    res = client.put(f"/theses/{thesis_id}", json=edit, headers=h)
    assert res.status_code == 200
    new = res.json()
    assert new["id"] != str(thesis_id) and new["version"] == 2 and new["status"] == "draft"
    assert [d["company_name"] for d in new["deals"]] == ["Kirana Cloud"]
    assert new["deals"][0]["match_rule"] == "partner_added"
    source = db.get(Source, uuid.UUID(new["deals"][0]["source_id"]))
    assert source and source.kind == "web" and source.endpoint_or_url == "https://news.example/k"

    confirmed = client.post(f"/theses/{new['id']}/confirm", headers=h).json()
    assert confirmed["status"] == "confirmed"
    assert client.get(f"/theses/{thesis_id}", headers=h).json()["status"] == "draft"


def test_profile_get_edit_confirm(client: TestClient, db: Session) -> None:
    investor, _, profile_id, _ = seed(db)
    h = {"X-Investor-Id": str(investor.id)}

    got = client.get(f"/scoring-profiles/{profile_id}", headers=h).json()
    assert got["origin"] == "generic" and got["derivation"][0]["target"] == "profile"

    criteria = [dict(c) for c in got["criteria"]]
    criteria[0]["weight"], criteria[1]["weight"] = 0.30, 0.15
    body = {"criteria": criteria, "thresholds": got["thresholds"]}
    new = client.put(f"/scoring-profiles/{profile_id}", json=body, headers=h).json()
    assert new["id"] != str(profile_id) and new["version"] == 2
    assert new["origin"] == "edited" and new["criteria"][0]["weight"] == 0.30

    criteria[0]["weight"] = 0.9
    bad = client.put(f"/scoring-profiles/{profile_id}", json=body | {"criteria": criteria},
                     headers=h)
    assert bad.status_code == 422

    confirmed = client.post(f"/scoring-profiles/{new['id']}/confirm", headers=h).json()
    assert confirmed["status"] == "confirmed"
    assert client.post(f"/scoring-profiles/{uuid.uuid4()}/confirm", headers=h
                       ).status_code == 404
