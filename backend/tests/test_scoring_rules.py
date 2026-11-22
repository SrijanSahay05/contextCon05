from datetime import date
from typing import Any

from app.services.scoring import rules as r
from app.services.scoring.rules import UNKNOWN, Evidence, Item

AS_OF = date(2026, 11, 1)
FOUNDER = "11111111-1111-1111-1111-111111111111"
THESIS: list[dict[str, Any]] = [
    {"dimension": "sectors", "value": {"shares": {"fintech": 0.6, "saas": 0.4},
                                       "top_sectors": ["fintech"]}},
    {"dimension": "stage", "value": {"seed": 0.7, "pre_seed": 0.3}},
    {"dimension": "geography", "value": {"countries": {"India": 1.0}}},
    {"dimension": "check_size", "value": {"max_usd": 2_000_000}},
    {"dimension": "entry_profile", "value": {"median_headcount": 20}},
]
_ids = iter(range(1, 10_000))


def f(predicate: str, value: Any, as_of: date | None = None, subject: str = "company",
      tier: str = "A") -> Item:
    return Item(next(_ids), predicate, value, as_of, subject, tier=tier)


def ev(*items: Item, thesis: list[dict[str, Any]] | None = None, **params: Any) -> Evidence:
    return Evidence(list(items), AS_OF, THESIS if thesis is None else thesis, params)


def test_every_rule_is_unknown_without_evidence() -> None:
    for name, rule in r.RULES.items():
        assert rule(ev()).score == UNKNOWN, name


def test_thesis_match_full_fit_cites_facts() -> None:
    items = [f("industries", ["Fintech"]), f("last_round_type", "seed"),
             f("hq_country", "India")]
    res = r.thesis_match(ev(*items))
    assert res.score == 100
    assert set(res.fact_ids) == {int(i.id) for i in items}


def test_thesis_match_exclusion_caps_at_zero() -> None:
    thesis = THESIS + [{"dimension": "exclusion", "value": "crypto, lending"}]
    res = r.thesis_match(ev(f("industries", ["Fintech", "Crypto"]), f("hq_country", "India"),
                            thesis=thesis))
    assert res.score == 0 and res.exclusion == "crypto"


def test_thesis_match_unknown_without_thesis_and_bonus_applies() -> None:
    assert r.thesis_match(ev(f("industries", ["fintech"]), thesis=[])).score == UNKNOWN
    outside = r.thesis_match(ev(f("industries", ["saas"]))).score
    boosted = r.thesis_match(ev(f("industries", ["saas"]), trend_bonus={"saas": 0.1})).score
    assert outside == 60 and boosted == 70


def _job(title: str, company: str, start: str, end: str | None = None) -> Item:
    return f("employment", {"title": title, "company_name": company, "start": start, "end": end},
             date.fromisoformat(start), subject=FOUNDER)


def test_team_signals_years_and_prior_founding() -> None:
    res = r.team_signals(ev(_job("Co-founder", "OldCo", "2015-01-01", "2019-01-01"),
                            _job("Product Manager", "Acme", "2019-02-01")))
    # base 20 + prior founding 20 + ≥5 years 30
    assert res.score == 70 and len(res.fact_ids) == 2


def test_team_pedigree_ignored_by_default() -> None:
    items = [_job("Analyst", "Google", "2026-06-01"),
             f("education", {"school": "IIT Bombay"}, subject=FOUNDER)]
    assert r.team_signals(ev(*items)).score == 20
    assert r.team_signals(ev(*items, use_pedigree=True)).score == 30


def test_facts_after_as_of_are_ignored() -> None:
    later = date(2027, 1, 1)
    assert r.market_signals(ev(f("competitors", ["a.com"], later))).score == UNKNOWN
    res = r.team_signals(ev(_job("Engineer", "X", "2026-12-01")))
    assert res.score == UNKNOWN


def test_growth_signals_against_benchmark() -> None:
    points = [f("headcount_at", 20, date(2026, 4, 1)), f("headcount_at", 26, date(2026, 10, 1))]
    res = r.growth_signals(ev(*points))
    assert res.score == 75  # +30% = the default benchmark
    assert r.growth_signals(ev(points[0])).score == UNKNOWN


def test_growth_signals_entry_benchmark_and_hiring() -> None:
    points = [f("headcount_at", 20, date(2026, 4, 1)), f("headcount_at", 20, date(2026, 10, 1))]
    role = f("open_roles", {"title": "SDE", "function": "engineering",
                            "posted_at": "2026-10-10"}, date(2026, 10, 10))
    res = r.growth_signals(ev(*points, role, benchmark="median_headcount_at_entry"))
    assert res.score == 50 + 2  # flat growth (50) and size = median (50), one open role


def test_funding_stage_fit() -> None:
    res = r.funding_stage_fit(ev(
        f("last_round_type", "seed"),
        f("funding_round", {"round_type": "seed", "amount_usd": 1_000_000}, date(2026, 6, 1)),
        f("grant", {"program": "BIRAC BIG"}, date(2026, 1, 1)),
    ))
    assert res.score == 100  # stage fit 50 + recent raise 25 + grant 25
    late = r.funding_stage_fit(ev(f("last_round_type", "series_c")))
    assert late.score == 20


def test_market_and_momentum() -> None:
    assert r.market_signals(ev(f("competitors", ["a", "b"]))).score == 80
    assert r.market_signals(ev(f("competitors", [str(i) for i in range(12)]))).score == 40
    news = [f("news_item", {"title": "Launch"}, date(2026, 10, 15)),
            f("news_item", {"title": "Old"}, date(2025, 1, 1))]
    assert r.recent_events(ev(*news)).score == 30 + 15 + 15
    assert r.recent_events(ev(news[1])).score == 20


def test_technical_depth_and_capital_efficiency() -> None:
    res = r.technical_depth(ev(_job("Software Engineer", "X", "2022-11-01", "2024-11-01")))
    assert res.score == 60  # 40 + 2 years × 10
    eff = r.capital_efficiency(ev(f("funding_total_usd", 2_000_000), f("headcount_total", 20)))
    assert eff.score == 75  # $100k per head = the benchmark
