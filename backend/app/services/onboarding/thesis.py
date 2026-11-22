"""Deterministic thesis inference: counts over the fund's deals, each point citing them."""

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.models.enums import Confidence

TREND_RECENT_MONTHS = 6
TREND_PRIOR_MONTHS = 12
TREND_MIN_DEALS = 3
TREND_MIN_SHARE_CHANGE = 0.10
TOP_SECTOR_COVERAGE = 0.70


@dataclass
class DealInput:
    """One deal with the company's profile at the round date (see `deals.entry_profile`)."""

    id: str
    company_id: str
    round_date: date | None
    round_type: str | None = None
    amount_usd: float | None = None
    led: bool | None = None
    sectors: list[str] = field(default_factory=list)
    country: str | None = None
    city: str | None = None
    age_years: float | None = None
    headcount: int | None = None
    championed: bool = False
    entry: bool = True  # False for a follow-on round in a company the firm already backed


@dataclass
class ThesisResult:
    window_start: date
    window_end: date
    deal_ids: list[str]
    confidence: Confidence
    points: list[dict[str, Any]]

    @property
    def deal_count(self) -> int:
        return len(self.deal_ids)


def months_before(d: date, months: int) -> date:
    total = d.year * 12 + d.month - 1 - months
    return date(total // 12, total % 12 + 1, min(d.day, 28))


def confidence_for(count: int) -> Confidence:
    if count >= 10:
        return Confidence.high
    return Confidence.medium if count >= 5 else Confidence.low


def _pct(share: float) -> str:
    return f"{round(share * 100)}%"


def _shares(counts: Counter[str], total: int) -> dict[str, float]:
    return {k: round(v / total, 2) for k, v in counts.most_common()}


def _sector(deal: DealInput) -> str:
    return deal.sectors[0] if deal.sectors else "unknown"


def _point(dimension: str, statement: str, value: Any, deals: list[DealInput]) -> dict[str, Any]:
    return {"dimension": dimension, "statement": statement, "value": value,
            "deal_ids": [d.id for d in deals]}


def _stage_label(round_type: str | None) -> str:
    if not round_type or round_type in {"unknown", "series_unknown"}:
        return "undisclosed round"
    return round_type


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _trend(deals: list[DealInput], end: date) -> dict[str, Any] | None:
    split = months_before(end, TREND_RECENT_MONTHS)
    start = months_before(split, TREND_PRIOR_MONTHS)
    recent = [d for d in deals if d.round_date and split < d.round_date <= end]
    prior = [d for d in deals if d.round_date and start < d.round_date <= split]
    if not recent or not prior:
        return None
    shifts: list[dict[str, Any]] = []
    involved: list[DealInput] = []
    for kind, key_of in (("sector", _sector), ("stage", lambda d: d.round_type or "unknown")):
        for key in sorted({key_of(d) for d in recent + prior}):
            r = [d for d in recent if key_of(d) == key]
            p = [d for d in prior if key_of(d) == key]
            recent_share, prior_share = len(r) / len(recent), len(p) / len(prior)
            if len(r) + len(p) < TREND_MIN_DEALS:
                continue
            if abs(recent_share - prior_share) < TREND_MIN_SHARE_CHANGE:
                continue
            shifts.append({
                "kind": kind, "key": key,
                "direction": "rising" if recent_share > prior_share else "falling",
                "recent_share": round(recent_share, 2), "prior_share": round(prior_share, 2),
                "deal_ids": [d.id for d in r + p],
            })
            involved += [d for d in r + p if d not in involved]
    if not shifts:
        return None
    statement = "; ".join(
        f"{s['key']} {s['direction']}: {_pct(s['recent_share'])} of deals in the last "
        f"{TREND_RECENT_MONTHS} months vs {_pct(s['prior_share'])} in the "
        f"{TREND_PRIOR_MONTHS} before" for s in shifts
    )
    return _point("trend", statement, {"shifts": shifts}, involved)


def infer_thesis(
    all_deals: list[DealInput],
    window_end: date,
    window_months: int = 18,
    partner_past_sectors: list[str] | None = None,
) -> ThesisResult:
    start = months_before(window_end, window_months)
    in_window = [d for d in all_deals if d.round_date and start <= d.round_date <= window_end]
    # follow-ons describe old bets, not what the firm invests in now: only entries count
    deals = [d for d in in_window if d.entry]
    follow_ons = len(in_window) - len(deals)
    n = len(deals)
    points: list[dict[str, Any]] = []
    if n:
        sectors = Counter(_sector(d) for d in deals)
        top, covered = [], 0
        for key, count in sectors.most_common():
            top.append(key)
            covered += count
            if covered / n >= TOP_SECTOR_COVERAGE:
                break
        points.append(_point(
            "sectors", f"{_pct(covered / n)} of deals are {' or '.join(top)}",
            {"shares": _shares(sectors, n), "top_sectors": top,
             "top_share": round(covered / n, 2)},
            deals,
        ))

        stages = Counter(_stage_label(d.round_type) for d in deals)
        statement = ", ".join(f"{_pct(v / n)} {k}" for k, v in stages.most_common())
        if follow_ons:
            statement += f" ({follow_ons} follow-on rounds in existing portfolio not counted)"
        points.append(_point(
            "stage", statement, _shares(stages, n) | {"follow_on_rounds": follow_ons}, deals,
        ))

        priced = [d for d in deals if d.amount_usd is not None]
        lead_known = [d for d in deals if d.led is not None]
        led = [d for d in lead_known if d.led]
        if priced or lead_known:
            amounts = [float(d.amount_usd) for d in priced if d.amount_usd is not None]
            value: dict[str, Any] = {
                "median_usd": _median(amounts),
                "min_usd": min(amounts) if amounts else None,
                "max_usd": max(amounts) if amounts else None,
                "lead_share": round(len(led) / len(lead_known), 2) if lead_known else None,
            }
            parts = []
            if amounts:
                parts.append(f"Median round ${value['median_usd'] / 1e6:.1f}M (range "
                             f"${min(amounts) / 1e6:.1f}M–${max(amounts) / 1e6:.1f}M)")
            if lead_known:
                parts.append(f"led {len(led)} of {len(lead_known)} deals")
            points.append(_point("check_size", "; ".join(parts), value, priced or lead_known))

        located = [d for d in deals if d.country]
        if located:
            countries = Counter(d.country or "" for d in located)
            cities = Counter(d.city for d in located if d.city)
            points.append(_point(
                "geography",
                ", ".join(f"{_pct(v / len(located))} {k}" for k, v in countries.most_common()),
                {"countries": _shares(countries, len(located)),
                 "cities": _shares(cities, sum(cities.values())) if cities else {}},
                located,
            ))

        ages = [d.age_years for d in deals if d.age_years is not None]
        heads = [float(d.headcount) for d in deals if d.headcount is not None]
        if ages or heads:
            value = {"median_age_years": _median(ages), "median_headcount": _median(heads)}
            parts = []
            if ages:
                parts.append(f"median company age {value['median_age_years']:g} years")
            if heads:
                parts.append(f"median headcount {value['median_headcount']:g}")
            points.append(_point(
                "entry_profile", "At entry: " + ", ".join(parts), value,
                [d for d in deals if d.age_years is not None or d.headcount is not None],
            ))

        trend = _trend(deals, window_end)
        if trend:
            points.append(trend)

    championed = [d for d in deals if d.championed]
    if championed or partner_past_sectors:
        value = {
            "sectors": dict(Counter(_sector(d) for d in championed)),
            "stages": dict(Counter(d.round_type or "unknown" for d in championed)),
            "past_sectors": sorted(set(partner_past_sectors or [])),
        }
        parts = []
        if championed:
            parts.append(f"The partner championed {len(championed)} deals in "
                         + ", ".join(value["sectors"]))
        if value["past_sectors"]:
            parts.append("previously worked in " + ", ".join(value["past_sectors"]))
        points.append(_point("partner_lens", "; ".join(parts), value, championed))

    return ThesisResult(start, window_end, [d.id for d in deals], confidence_for(n), points)


def summary_sentence(result: ThesisResult) -> str:
    """Deterministic summary: only repeats the statements of the computed points."""
    by_dim = {p["dimension"]: p["statement"] for p in result.points}
    parts = [by_dim[k] for k in ("sectors", "stage", "check_size", "geography") if k in by_dim]
    text = ". ".join(parts) or "No deals found in the window"
    return f"{text} ({result.deal_count} deals, {result.confidence.value} confidence)."
