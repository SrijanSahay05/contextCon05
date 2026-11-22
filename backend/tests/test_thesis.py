from datetime import date

from app.models.enums import Confidence
from app.services.onboarding.thesis import DealInput, infer_thesis, summary_sentence

END = date(2026, 11, 1)


def deal(i: int, when: date, sector: str = "fintech", stage: str = "seed",
         **kw: object) -> DealInput:
    return DealInput(id=f"d{i}", company_id=f"c{i}", round_date=when, round_type=stage,
                     sectors=[sector], **kw)  # type: ignore[arg-type]


def test_confidence_bands() -> None:
    def conf(n: int) -> Confidence:
        return infer_thesis([deal(i, date(2026, 6, 1)) for i in range(n)], END).confidence

    assert conf(10) == Confidence.high
    assert conf(9) == Confidence.medium
    assert conf(5) == Confidence.medium
    assert conf(4) == Confidence.low


def test_deals_outside_window_are_ignored() -> None:
    result = infer_thesis([deal(1, date(2026, 6, 1)), deal(2, date(2024, 1, 1))], END)
    assert result.deal_ids == ["d1"]
    assert infer_thesis([deal(2, date(2024, 1, 1))], END, 36).deal_ids == ["d2"]


def test_every_point_cites_deals_and_top_sectors_cover_70pct() -> None:
    deals = [deal(i, date(2026, 3, 1), "fintech", amount_usd=1e6 * (i + 1), led=i < 3,
                  country="India", city="Bengaluru", age_years=2, headcount=10 + i)
             for i in range(5)]
    deals += [deal(5, date(2026, 3, 1), "saas"), deal(6, date(2026, 3, 1), "agritech"),
              deal(7, date(2026, 3, 1), "saas")]
    result = infer_thesis(deals, END)
    assert all(p["deal_ids"] for p in result.points)
    sectors = next(p for p in result.points if p["dimension"] == "sectors")
    # fintech 62.5% alone is < 70%, so saas is added
    assert sectors["value"]["top_sectors"] == ["fintech", "saas"]
    assert sectors["value"]["top_share"] == 0.88
    check = next(p for p in result.points if p["dimension"] == "check_size")
    assert check["value"]["median_usd"] == 3e6 and check["value"]["lead_share"] == 0.6
    assert {p["dimension"] for p in result.points} >= {
        "sectors", "stage", "check_size", "geography", "entry_profile"}
    assert "8 deals" in summary_sentence(result)


def test_trend_shift_needs_three_deals() -> None:
    prior = [deal(i, date(2025, 9, 1), "saas") for i in range(3)]
    two_recent = [deal(10, date(2026, 9, 1), "climate"), deal(11, date(2026, 9, 1), "saas")]
    result = infer_thesis(prior + two_recent, END)
    trend = next(p for p in result.points if p["dimension"] == "trend")
    keys = {s["key"] for s in trend["value"]["shifts"]}
    assert "climate" not in keys  # only 1 deal involved
    assert "saas" in keys  # 4 deals involved, share fell from 100% to 50%

    small = infer_thesis([deal(1, date(2025, 9, 1), "saas"),
                          deal(2, date(2026, 9, 1), "climate")], END)
    assert not any(p["dimension"] == "trend" for p in small.points)


def test_partner_lens_from_championed_deals() -> None:
    deals = [deal(1, date(2026, 3, 1), championed=True), deal(2, date(2026, 3, 1))]
    lens = next(p for p in infer_thesis(deals, END, partner_past_sectors=["payments"]).points
                if p["dimension"] == "partner_lens")
    assert lens["deal_ids"] == ["d1"] and lens["value"]["past_sectors"] == ["payments"]
