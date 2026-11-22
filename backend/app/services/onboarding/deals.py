"""Strict round matching: which of a company's funding rounds are the fund's deals.

Pure functions over a Crustdata `company/enrich` `company_data` object.
"""

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from app.services.onboarding.names import normalize_name, round_names_firm

EXACT = "exact_round_name"


@dataclass
class DealDraft:
    """A matched round. `flag` is None for a countable deal, "date_unknown" when the firm is
    on the company but no round names it, "held" when the name is ambiguous across permalinks."""

    round_date: date | None
    round_type: str | None
    amount_usd: float | None
    led: bool | None
    match_rule: str
    match_evidence: dict[str, Any]
    flag: str | None = None


@dataclass
class EntryProfile:
    """The company as it was at the round date."""

    sectors: list[str] = field(default_factory=list)
    stage: str | None = None
    amount_usd: float | None = None
    country: str | None = None
    city: str | None = None
    age_years: float | None = None
    headcount: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _round_date(milestone: dict[str, Any]) -> date | None:
    return parse_date(milestone.get("funding_date") or milestone.get("date"))


def deals_from_company(
    company_data: dict[str, Any],
    canonical_names: set[str],
    permalinks: set[str],
    window: tuple[date, date],
) -> list[DealDraft]:
    funding = company_data.get("funding") or {}
    detailed = [
        d for d in funding.get("investors_detailed") or [] if d.get("permalink") in permalinks
    ]
    if not detailed:
        return []

    named = [
        (m, name) for m in funding.get("milestones") or []
        if (name := round_names_firm(m.get("investors"), canonical_names)) is not None
    ]
    drafts: list[DealDraft] = []
    for milestone, matched in named:
        round_date = _round_date(milestone)
        if round_date is None or not window[0] <= round_date <= window[1]:
            continue
        same_name = {
            d["permalink"] for d in detailed
            if normalize_name(d.get("name") or "") == normalize_name(matched)
        }
        evidence: dict[str, Any] = {
            "round_investors": milestone.get("investors"), "matched_name": matched,
        }
        if len(same_name) > 1:
            evidence["permalinks"] = sorted(same_name)
        amount = milestone.get("amount_usd")
        drafts.append(DealDraft(
            round_date=round_date,
            round_type=milestone.get("round_type"),
            amount_usd=float(amount) if amount is not None else None,
            led=round_names_firm(milestone.get("lead_investors"), canonical_names) is not None,
            match_rule=EXACT,
            match_evidence=evidence,
            flag="held" if len(same_name) > 1 else None,
        ))

    if not any(_round_date(m) for m, _ in named):
        drafts.append(DealDraft(
            round_date=None, round_type=None, amount_usd=None, led=None,
            match_rule="portfolio_date_unknown",
            match_evidence={"permalinks": sorted(d["permalink"] for d in detailed)},
            flag="date_unknown",
        ))
    return drafts


def _sectors(company_data: dict[str, Any]) -> list[str]:
    taxonomy = company_data.get("taxonomy") or {}
    basic = company_data.get("basic_info") or {}
    sectors = (
        taxonomy.get("professional_network_industries")
        or ([taxonomy["professional_network_industry"]]
            if taxonomy.get("professional_network_industry") else [])
        or taxonomy.get("categories")
        or basic.get("industries")
        or []
    )
    return [str(s) for s in sectors if s]


def entry_profile(company_data: dict[str, Any], round_date: date) -> EntryProfile:
    basic = company_data.get("basic_info") or {}
    locations = company_data.get("locations") or {}
    headcount = company_data.get("headcount") or {}
    funding = company_data.get("funding") or {}

    milestone: dict[str, Any] = next(
        (m for m in funding.get("milestones") or [] if _round_date(m) == round_date), {}
    )
    points = sorted(
        (d, p.get("employee_count"))
        for p in headcount.get("timeseries") or []
        if (d := parse_date(p.get("date"))) and d <= round_date
    )
    founded = basic.get("year_founded")
    amount = milestone.get("amount_usd")
    return EntryProfile(
        sectors=_sectors(company_data),
        stage=milestone.get("round_type"),
        amount_usd=float(amount) if amount is not None else None,
        country=locations.get("country") or headcount.get("largest_headcount_country") or None,
        city=locations.get("city") or None,
        age_years=round(round_date.year - int(founded), 1) if founded else None,
        headcount=points[-1][1] if points else None,
    )
