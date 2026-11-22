import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.scout_params import (
    SIGNALS,
    EvidenceKind,
    EvidenceRef,
    InferenceConfig,
    InvestorIdentity,
    Lens,
    Origin,
    ScoutRequest,
    SignalKey,
    SignalNudge,
    Weight,
    default_request,
    infer_weights,
    lens_base_weights,
    lens_weights,
    panel_order,
    reset_weights,
    set_locked,
    set_weight,
)

EXAMPLE = Path(__file__).parent / "fixtures" / "scout_request.example.json"


def total(ws: list[Weight]) -> float:
    return round(sum(w.value for w in ws), 2)


def investor() -> InvestorIdentity:
    return InvestorIdentity(
        name="Test Investor",
        firm="Example Ventures",
        linkedin_url="https://www.linkedin.com/in/test-investor/?utm=x",
        consent=True,
    )


@pytest.mark.parametrize("lens", list(Lens))
def test_lens_weights_sum_to_100_and_cover_all_signals(lens: Lens) -> None:
    base = lens_base_weights(lens)
    assert set(base) == set(SIGNALS)
    assert abs(sum(base.values()) - 100) < 1e-9
    assert total(lens_weights(lens)) == 100


def test_default_request_profile_path() -> None:
    req = default_request(investor=investor())
    assert req.investor is not None
    assert req.investor.linkedin_url == (
        "https://www.linkedin.com/in/test-investor"
    )
    assert total(req.ranking.weights) == 100


def test_request_needs_an_entry_point() -> None:
    with pytest.raises(ValidationError, match="provide `investor`"):
        default_request()
    assert default_request(thesis_text="logistics SaaS in India").thesis_text


def test_consent_required() -> None:
    with pytest.raises(ValidationError, match="consent"):
        InvestorIdentity(
            name="A B", firm="F V",
            linkedin_url="https://linkedin.com/in/ab", consent=False,
        )


def test_non_profile_linkedin_rejected() -> None:
    with pytest.raises(ValidationError):
        InvestorIdentity(
            name="A B", firm="F V",
            linkedin_url="https://linkedin.com/company/fv", consent=True,
        )


def test_protected_attributes_rejected() -> None:
    data = default_request(thesis_text="x").model_dump(mode="json")
    data["founders"]["college_tier"] = "tier_1"
    with pytest.raises(ValidationError, match="protected attribute"):
        ScoutRequest.model_validate(data)


def test_unknown_signal_rejected() -> None:
    data = default_request(thesis_text="x").model_dump(mode="json")
    data["ranking"]["weights"][0]["signal"] = "college"
    with pytest.raises(ValidationError):
        ScoutRequest.model_validate(data)


def test_weights_must_sum_to_100() -> None:
    data = default_request(thesis_text="x").model_dump(mode="json")
    data["ranking"]["weights"][0]["value"] += 10
    with pytest.raises(ValidationError, match="sum to 100"):
        ScoutRequest.model_validate(data)


def test_infer_weights_moves_nudged_signal_and_respects_cap() -> None:
    ev = EvidenceRef(kind=EvidenceKind.PORTFOLIO_STAT, ref="portfolio:tech")
    cfg = InferenceConfig(max_weight=12)
    ws = infer_weights(
        Lens.PRE_ROUND,
        portfolio_nudges=[SignalNudge(
            SignalKey.TECHNICAL_COFOUNDER, 1.0,
            "72% of portfolio vs 45% of cohort", [ev],
        )],
        post_nudges=[SignalNudge(
            SignalKey.HEADCOUNT_GROWTH_6M, 1.0, "9 posts on scaling teams",
        )],
        config=cfg,
    )
    by = {w.signal: w for w in ws}
    tech = by[SignalKey.TECHNICAL_COFOUNDER]
    assert tech.value > tech.base
    assert tech.origin is Origin.INFERRED
    assert tech.evidence == [ev]
    assert all(w.value <= cfg.max_weight for w in ws)
    assert total(ws) == 100


def test_set_weight_rebalances_and_keeps_locked() -> None:
    ws = lens_weights(Lens.PRE_ROUND)
    ws = set_locked(ws, SignalKey.RUNWAY_PRESSURE, True)
    locked_before = next(
        w.value for w in ws if w.signal == SignalKey.RUNWAY_PRESSURE
    )
    ws = set_weight(ws, SignalKey.DOMAIN_YEARS, 30)
    by = {w.signal: w for w in ws}
    assert by[SignalKey.DOMAIN_YEARS].value == 30
    assert by[SignalKey.DOMAIN_YEARS].origin is Origin.INVESTOR
    assert by[SignalKey.RUNWAY_PRESSURE].value == locked_before
    assert total(ws) == 100
    assert panel_order(ws, 1)[0].signal == SignalKey.DOMAIN_YEARS


def test_reset_returns_to_base() -> None:
    ws = set_weight(lens_weights(Lens.MOMENTUM), SignalKey.DOMAIN_YEARS, 40)
    ws = reset_weights(ws)
    assert all(abs(w.value - w.base) < 0.02 for w in ws)
    assert total(ws) == 100


def test_example_file_validates() -> None:
    req = ScoutRequest.model_validate(json.loads(EXAMPLE.read_text()))
    assert req.ranking.lens is Lens.FOUNDER_FIRST


def test_json_schema_exports() -> None:
    schema = ScoutRequest.model_json_schema()
    assert "ranking" in schema["properties"]
