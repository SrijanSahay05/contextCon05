from datetime import date

from app.models.enums import VerificationResult
from app.services.scoring.engine import Profile, score
from app.services.scoring.rules import UNKNOWN, Evidence, Item

AS_OF = date(2026, 11, 1)
THRESH = {"reach_out": 65, "watch": 45, "min_completeness": 0.5}
MARKET = {"key": "market", "weight": 0.6, "rule": "market_signals", "params": {}}
TRACTION = {"key": "traction", "weight": 0.4, "rule": "growth_signals", "params": {}}
PROFILE = Profile([MARKET, TRACTION], THRESH)


def comp(tier: str = "A") -> Item:  # 2 competitors → raw market score 80
    return Item(1, "competitors", ["a.com", "b.com"], None, tier=tier)


def heads(*values_and_dates: tuple[int, date], tier: str = "A") -> list[Item]:
    return [Item(10 + n, "headcount_at", v, d, tier=tier)
            for n, (v, d) in enumerate(values_and_dates)]


def claim(value: int, result: VerificationResult | None) -> Item:
    return Item("c1", "headcount", value, date(2026, 10, 1), verification=result)


def by_key(items: list[Item], profile: Profile = PROFILE) -> dict[str, object]:
    return {c.key: c.score for c in score(Evidence(items, AS_OF), profile).criteria}


def test_unknown_excluded_and_completeness() -> None:
    b = score(Evidence([comp()], AS_OF), PROFILE)
    assert b.unknown == ["traction"]
    assert b.score == 80 and b.completeness == 0.6


def test_all_unknown_gives_no_score() -> None:
    b = score(Evidence([], AS_OF), PROFILE)
    assert b.score is None and b.completeness == 0


def test_source_tier_multiplier() -> None:
    assert by_key([comp("B")])["market"] == 50 + 30 * 0.8
    tiers = Profile([MARKET], THRESH, source_tiers={"A": 1.0, "B": 1.0, "C": 0.2})
    assert by_key([comp("C")], tiers)["market"] == 50 + 30 * 0.2


def test_self_reported_claim_weighted() -> None:
    base = heads((20, date(2026, 4, 1)))
    # claim makes 20 → 26: raw 75; evidence weight = mean(fact 1.0, claim 0.5) = 0.75
    mixed = score(Evidence(base + [claim(26, None)], AS_OF), PROFILE).criteria[1]
    assert mixed.evidence_weight == 0.75 and mixed.claim_ids == ("c1",)
    assert abs(float(mixed.score) - (50 + 25 * 0.75)) <= 0.05
    verified = by_key(base + [claim(26, VerificationResult.verified)])
    assert verified["traction"] == 75
    only_claims = Profile([TRACTION], THRESH, self_reported_weight=0.5)
    two = [Item("c0", "headcount", 20, date(2026, 4, 1)), claim(26, None)]
    res = score(Evidence(two, AS_OF), only_claims).criteria[0]
    assert res.self_reported_only and res.score == 62.5


def test_contradicted_claim_penalised_not_used() -> None:
    items = heads((20, date(2026, 4, 1)), (26, date(2026, 10, 1)))
    res = score(Evidence(items + [claim(60, VerificationResult.contradicted)], AS_OF),
                PROFILE).criteria[1]
    assert res.score == 75 - 15  # the claim's 60 is ignored; default penalty 15
    assert res.contradicted_claim_ids == ("c1",) and "c1" in res.claim_ids
    custom = Profile([TRACTION], THRESH | {"contradiction_penalty": 30})
    assert score(Evidence(items + [claim(60, VerificationResult.contradicted)], AS_OF),
                 custom).criteria[0].score == 45


def test_exclusion_not_shrunk_by_tier() -> None:
    thesis = [{"dimension": "exclusion", "value": "crypto"}]
    profile = Profile([{"key": "thesis_fit", "weight": 1, "rule": "thesis_match"}], THRESH)
    b = score(Evidence([Item(1, "industries", ["Crypto"], None, tier="C")], AS_OF, thesis),
              profile)
    assert b.score == 0 and b.exclusion == "crypto"


def test_unknown_rule_is_unknown_and_deterministic() -> None:
    odd = Profile([{"key": "x", "weight": 1, "rule": "nope"}], THRESH)
    assert by_key([comp()], odd)["x"] == UNKNOWN
    items = [comp()] + heads((20, date(2026, 4, 1)), (26, date(2026, 10, 1)))
    generic = Profile.generic()
    assert score(Evidence(items, AS_OF), generic) == score(Evidence(items[::-1], AS_OF), generic)
