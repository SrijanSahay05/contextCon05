"""Strong signals, red flags and gaps from the evidence and the breakdown. Pure.

Every signal cites the facts and claims behind it; every gap names the data that would
settle it.
"""

from dataclasses import dataclass

from app.models.enums import SignalKind, VerificationResult
from app.services.evidence import facts_mapper as fm
from app.services.scoring.engine import Breakdown
from app.services.scoring.rules import (
    GAP_DATA,
    GRANT,
    UNKNOWN,
    Evidence,
    Item,
    founder_years,
    headcount_change,
    months_before,
)

STRONG_GROWTH = 0.5
DECLINE = -0.2
FOUNDER_YEARS = 5
ENTRY_SIZE_FAR = 10  # headcount multiple of the fund's median at entry
TIER1_INVESTORS = ("sequoia", "peak xv", "accel", "lightspeed", "elevation", "blume",
                   "nexus", "matrix", "kalaari", "a16z", "andreessen", "y combinator",
                   "tiger global", "general catalyst", "index ventures", "benchmark")


@dataclass(frozen=True)
class SignalDraft:
    kind: SignalKind
    text: str
    fact_ids: tuple[int, ...] = ()
    claim_ids: tuple[str, ...] = ()


def _cite(kind: SignalKind, text: str, items: list[Item]) -> SignalDraft:
    return SignalDraft(kind, text, tuple(sorted({int(i.id) for i in items if not i.is_claim})),
                       tuple(sorted({str(i.id) for i in items if i.is_claim})))


def _founder_name(ev: Evidence, person: str) -> str:
    names = ev.get(fm.NAME, subject=person)
    return str(names[-1].value) if names else "A founder"


def signals_for(ev: Evidence, breakdown: Breakdown, window_months: int = 6
                ) -> list[SignalDraft]:
    out: list[SignalDraft] = []
    strong, red = SignalKind.strong, SignalKind.red_flag

    change = headcount_change(ev, window_months)
    if change:
        growth, first, last = change
        span = f"{first.value} → {last.value} ({growth:+.0%}) since {first.as_of}"
        if growth >= STRONG_GROWTH:
            out.append(_cite(strong, f"Headcount {span}", [first, last]))
        elif growth <= DECLINE:
            out.append(_cite(red, f"Headcount fell {span}", [first, last]))

    since = months_before(ev.as_of, window_months)
    for r in ev.get(fm.FUNDING_ROUND):
        leads = [str(x) for x in (r.value.get("lead_investors") or r.value.get("investors") or [])]
        tier1 = [x for x in leads if any(t in x.lower() for t in TIER1_INVESTORS)]
        if r.as_of and r.as_of >= since and tier1:
            out.append(_cite(strong, f"Recent {r.value.get('round_type') or 'round'} "
                             f"({r.as_of}) with {', '.join(tier1)}", [r]))

    for person in ev.founders():
        name = _founder_name(ev, person)
        years, jobs = founder_years(ev, person)
        if years >= FOUNDER_YEARS:
            out.append(_cite(strong, f"{name} has {years:.0f} years of experience", jobs))
        left = [j for j in jobs if ev.company_name and j.value.get("end")
                and str(j.value.get("company_name") or "").lower() == ev.company_name.lower()]
        if left:
            out.append(_cite(red, f"{name} left {ev.company_name} ({left[-1].value['end']})",
                             left))

    for g in ev.get(GRANT):
        if not g.is_claim or g.verification == VerificationResult.verified:
            out.append(_cite(strong, f"Verified grant: {g.value.get('program') or 'grant'}",
                             [g]))

    for c in breakdown.criteria:
        bad = [i for i in ev.items if str(i.id) in c.contradicted_claim_ids]
        for claim in bad:
            out.append(_cite(red, f"Claim contradicted: {claim.predicate} = {claim.value}",
                             [claim]))

    if not ev.get(fm.DOMAIN, fm.WEB_TRAFFIC_MONTHLY, fm.NEWS_ITEM):
        out.append(SignalDraft(red, "No web presence found (no domain, traffic or news)"))

    industries = [i for i in ev.get(fm.INDUSTRIES) if isinstance(i.value, list)]
    if len(industries) >= 2:
        old, new = industries[0], industries[-1]
        if not {str(v).lower() for v in old.value} & {str(v).lower() for v in new.value}:
            out.append(_cite(red, f"Sector changed: {', '.join(old.value)} → "
                             f"{', '.join(new.value)} (possible pivot)", [old, new]))

    entry = ev.thesis("entry_profile")
    median = (entry[0].get("value") or {}).get("median_headcount") if entry else None
    sizes = [i for i in ev.get(fm.HEADCOUNT_TOTAL) if isinstance(i.value, (int, float))]
    if median and sizes and sizes[-1].value >= ENTRY_SIZE_FAR * float(median):
        out.append(_cite(red, f"Far outside the fund's entry profile: {sizes[-1].value:g} "
                         f"people vs a median of {float(median):g} at entry", [sizes[-1]]))

    for c in breakdown.criteria:
        if c.score == UNKNOWN:
            out.append(SignalDraft(SignalKind.gap, f"{c.key} unknown: {c.reason}. Needs "
                                   f"{GAP_DATA.get(c.rule, 'more data')}.", c.fact_ids,
                                   c.claim_ids))
        elif c.self_reported_only:
            out.append(SignalDraft(SignalKind.gap, f"{c.key} rests only on self-reported "
                                   f"claims. Needs independent {GAP_DATA.get(c.rule, 'data')}.",
                                   c.fact_ids, c.claim_ids))
    return out
