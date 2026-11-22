import copy
import json
from datetime import date
from pathlib import Path
from typing import Any

from app.services.onboarding.deals import deals_from_company, entry_profile

FIXTURE = Path(__file__).parent / "fixtures" / "crustdata" / "company_enrich.json"
ALL_TIME = (date(2000, 1, 1), date(2030, 1, 1))


def lumen() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text())["response"][0]["matches"][0][
        "company_data"
    ]
    return copy.deepcopy(data)


def test_accel_rounds_count_and_accel_kkr_does_not() -> None:
    drafts = deals_from_company(lumen(), {"Accel"}, {"accel"}, ALL_TIME)
    assert [(d.round_type, d.flag) for d in drafts] == [("seed", None), ("series_a", None)]
    assert all(d.match_rule == "exact_round_name" for d in drafts)
    assert drafts[0].match_evidence == {
        "round_investors": "Accel, Angel Collective", "matched_name": "Accel",
    }


def test_accel_kkr_alias_only_gets_its_own_round() -> None:
    drafts = deals_from_company(lumen(), {"Accel-KKR"}, {"accel-kkr"}, ALL_TIME)
    assert [d.round_type for d in drafts] == ["private_equity"]


def test_lead_detection() -> None:
    seed, series_a = deals_from_company(lumen(), {"Accel"}, {"accel"}, ALL_TIME)
    assert seed.led is True
    assert series_a.led is False


def test_unconfirmed_permalink_gives_nothing() -> None:
    assert deals_from_company(lumen(), {"Accel"}, {"accel-india"}, ALL_TIME) == []


def test_firm_on_company_but_no_round_is_date_unknown() -> None:
    data = lumen()
    for milestone in data["funding"]["milestones"]:
        milestone["investors"] = milestone["investors"].replace("Accel, ", "").replace(
            ", Accel", "")
    drafts = deals_from_company(data, {"Accel"}, {"accel"}, ALL_TIME)
    assert [(d.flag, d.round_date) for d in drafts] == [("date_unknown", None)]


def test_one_name_under_two_confirmed_permalinks_is_held() -> None:
    data = lumen()
    data["funding"]["investors_detailed"].append(
        {"name": "Accel", "permalink": "accel-2", "type": "organization"}
    )
    drafts = deals_from_company(data, {"Accel"}, {"accel", "accel-2"}, ALL_TIME)
    assert {d.flag for d in drafts} == {"held"}
    assert drafts[0].match_evidence["permalinks"] == ["accel", "accel-2"]


def test_window_filters_rounds() -> None:
    drafts = deals_from_company(lumen(), {"Accel"}, {"accel"}, (date(2021, 1, 1), date(2022, 1, 1)))
    assert [d.round_type for d in drafts] == ["series_a"]
    # rounds exist but outside the window: no deals and not "date unknown"
    assert deals_from_company(lumen(), {"Accel"}, {"accel"},
                              (date(2024, 1, 1), date(2026, 1, 1))) == []


def test_entry_profile_headcount_at_round_date() -> None:
    profile = entry_profile(lumen(), date(2025, 2, 18))
    assert profile.headcount == 322  # the 2025-02-01 point, not the later ones
    assert profile.stage == "private_equity"
    assert profile.amount_usd == 120000000
    assert profile.age_years == 6
    assert profile.country == "United States"
    assert entry_profile(lumen(), date(2020, 3, 15)).headcount is None  # before the series
