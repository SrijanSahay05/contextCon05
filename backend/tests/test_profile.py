import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.models.enums import Confidence, ProfileOrigin
from app.services.onboarding.profile import (
    RULES_PATH,
    PartnerProfile,
    ProfileResult,
    derive_profile,
    load_rules,
    partner_from_person,
)
from app.services.onboarding.thesis import DealInput, infer_thesis

END = date(2026, 11, 1)
FIXTURES = Path(__file__).parent / "fixtures" / "crustdata"


def deals(stages: list[str], sectors: list[str] | None = None) -> list[DealInput]:
    sectors = sectors or [f"s{i}" for i in range(len(stages))]  # spread: no concentration
    return [DealInput(id=f"d{i}", company_id=f"c{i}", round_date=date(2026, 3, 1),
                      round_type=stage, sectors=[sectors[i]]) for i, stage in enumerate(stages)]


def derive(ds: list[DealInput], partner: PartnerProfile | None = None,
           rules: dict[str, Any] | None = None) -> ProfileResult:
    return derive_profile(ds, infer_thesis(ds, END), partner or PartnerProfile(), rules)


def weights(result: ProfileResult) -> dict[str, float]:
    return {c["key"]: c["weight"] for c in result.criteria}


def check_invariants(result: ProfileResult) -> None:
    assert sum(weights(result).values()) == pytest.approx(1, abs=1e-3)
    assert all(step["evidence_ids"] for step in result.derivation)


def test_seed_heavy_firm_is_team_heavy() -> None:
    result = derive(deals(["seed"] * 4 + ["pre_seed", "series_a"]))
    w = weights(result)
    assert w["team"] == pytest.approx(0.30) and w["traction"] == pytest.approx(0.10)
    assert result.origin == ProfileOrigin.derived
    traction = next(c for c in result.criteria if c["key"] == "traction")
    assert traction["params"]["benchmark"] == "median_headcount_at_entry"
    check_invariants(result)


def test_series_a_plus_firm_is_traction_heavy() -> None:
    w = weights(derive(deals(["series_a", "series_b", "series_a", "series_c", "seed"])))
    assert w["traction"] == pytest.approx(0.30) and w["funding"] == pytest.approx(0.15)
    assert w["team"] == pytest.approx(0.10) and w["market"] == pytest.approx(0.10)


def test_concentration_and_lead_renormalise() -> None:
    ds = deals(["seed"] * 5, ["fintech"] * 5)
    for d in ds:
        d.led = True
    result = derive(ds)
    targets = [s["target"] for s in result.derivation]
    assert "thesis_fit.weight" in targets and "weights" in targets
    check_invariants(result)


def test_engineering_partner_adds_technical_depth() -> None:
    partner = PartnerProfile(engineering_years=4, evidence_id="src-1")
    result = derive(deals(["seed"] * 5), partner)
    assert weights(result)["technical_depth"] > 0
    check_invariants(result)


def test_finance_and_founder_partner() -> None:
    partner = PartnerProfile(finance_background=True, was_founder=True, evidence_id="src-1")
    result = derive(deals(["seed"] * 5), partner)
    assert "capital_efficiency" in weights(result)
    team = next(c for c in result.criteria if c["key"] == "team")
    assert team["params"]["founder_market_fit"] is True
    check_invariants(result)


def test_partner_lens_needs_two_championed_deals_in_a_sector() -> None:
    ds = deals(["seed"] * 5, ["fintech", "fintech", "saas", "a", "b"])
    ds[0].championed = ds[1].championed = ds[2].championed = True
    fit = next(c for c in derive(ds).criteria if c["key"] == "thesis_fit")
    assert fit["params"]["partner_lens"] == {"fintech": 0.1}


def test_fewer_than_five_deals_is_generic_low_confidence() -> None:
    result = derive(deals(["seed"] * 4), PartnerProfile(engineering_years=10, evidence_id="x"))
    assert result.origin == ProfileOrigin.generic
    assert result.confidence == Confidence.low
    assert weights(result) == {"thesis_fit": 0.25, "team": 0.20, "traction": 0.20,
                               "funding": 0.10, "market": 0.15, "momentum": 0.10}
    assert "low confidence: generic profile" in result.derivation[0]["reason"]
    check_invariants(result)


def test_rules_come_from_the_json(tmp_path: Path) -> None:
    ds = deals(["seed"] * 3 + ["series_a"] * 2)  # 60% seed
    assert weights(derive(ds))["team"] == pytest.approx(0.30)
    rules = json.loads(RULES_PATH.read_text())
    rules["early_heavy"]["min_share"] = 0.8
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(rules))
    assert weights(derive(ds, rules=load_rules(path)))["team"] == pytest.approx(0.20)


def test_partner_from_person_enrich() -> None:
    fx = json.loads((FIXTURES / "person_enrich.json").read_text())
    person = fx["response"][0]["matches"][0]["person_data"]
    partner = partner_from_person(person, END)
    assert partner.was_founder  # "Co-founder & CEO"
    assert not partner.finance_background
    assert partner.engineering_years == 0  # "Product Manager" is not engineering
    person["experience"]["employment_details"]["past"].append(
        {"title": "Senior Software Engineer", "start_date": "2010-01-01",
         "end_date": "2014-01-01"})
    assert partner_from_person(person, END).engineering_years == pytest.approx(4, abs=0.1)
