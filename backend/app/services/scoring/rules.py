"""The criteria library: one pure, named function per profile `rule` key.

Every rule takes an `Evidence` bundle (facts and founder claims as `Item`s, the thesis
points, the `as_of` date and the criterion's `params`) and returns a `RuleResult`:
a 0–100 score or `"unknown"`, a short reason and the ids of the items it used.
Items dated after `as_of` are invisible (past-date replay); contradicted claims never
feed a score (the engine penalises them). No I/O, no LLM.
"""

import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from app.models.enums import VerificationResult
from app.services.evidence import facts_mapper as fm

UNKNOWN: Literal["unknown"] = "unknown"
Score = float | Literal["unknown"]

OPEN_ROLES = "open_roles"
GRANT = "grant"
# claim predicates that mean the same as a fact predicate
ALIASES = {"headcount": fm.HEADCOUNT_AT, "funding_total": fm.FUNDING_TOTAL_USD}

TECH_TITLE_WORDS = ("engineer", "developer", "cto", "architect", "scientist", "research",
                    "programmer", "tech lead", "technical")
TECH_FIELD_WORDS = ("computer", "engineering", "electrical", "electronics", "physics",
                    "mathematics", "data science", "machine learning", "chemistry", "biotech")
DEFAULT_PEDIGREE_SCHOOLS = ("iit", "bits", "iim", "stanford", "mit", "harvard", "berkeley",
                            "oxford", "cambridge", "wharton", "insead")
DEFAULT_PEDIGREE_COMPANIES = ("google", "microsoft", "amazon", "meta", "facebook", "apple",
                              "mckinsey", "bcg", "bain", "goldman sachs", "flipkart", "razorpay")


@dataclass(frozen=True)
class Item:
    """One piece of evidence: a fact (`tier` set) or a founder claim (`verification`)."""

    id: int | str
    predicate: str
    value: Any
    as_of: date | None
    subject: str = "company"  # "company", or the founder's person id
    tier: str | None = None
    verification: VerificationResult | None = None

    @property
    def is_claim(self) -> bool:
        return self.tier is None

    @property
    def contradicted(self) -> bool:
        return self.verification == VerificationResult.contradicted

    @property
    def kind(self) -> str:
        return ALIASES.get(self.predicate, self.predicate) if self.is_claim else self.predicate


@dataclass
class Evidence:
    items: list[Item]
    as_of: date
    thesis_points: list[dict[str, Any]] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    company_name: str = ""

    def visible(self) -> list[Item]:
        return sorted(
            (i for i in self.items if i.as_of is None or i.as_of <= self.as_of),
            key=lambda i: (i.as_of or date.min, str(i.id)),
        )

    def get(self, *predicates: str, subject: str | None = None) -> list[Item]:
        """Usable items for these predicates, oldest first (contradicted claims excluded)."""
        return [i for i in self.visible() if i.kind in predicates and not i.contradicted
                and (subject is None or i.subject == subject)]

    def contradicted(self, predicates: frozenset[str]) -> list[Item]:
        return [i for i in self.visible() if i.contradicted and i.kind in predicates]

    def founders(self) -> list[str]:
        return sorted({i.subject for i in self.visible() if i.subject != "company"})

    def thesis(self, dimension: str) -> list[dict[str, Any]]:
        return [p for p in self.thesis_points if p.get("dimension") == dimension]


@dataclass(frozen=True)
class RuleResult:
    score: Score
    reason: str
    fact_ids: tuple[int, ...] = ()
    claim_ids: tuple[str, ...] = ()
    exclusion: str | None = None  # thesis_match only: the exclusion that matched


def result(score: Score, reason: str, used: list[Item], exclusion: str | None = None
           ) -> RuleResult:
    if score != UNKNOWN:
        score = round(min(max(float(score), 0.0), 100.0), 1)
    return RuleResult(
        score, reason,
        tuple(sorted({int(i.id) for i in used if not i.is_claim})),
        tuple(sorted({str(i.id) for i in used if i.is_claim})),
        exclusion,
    )


def months_before(d: date, months: int) -> date:
    total = d.year * 12 + d.month - 1 - months
    return date(total // 12, total % 12 + 1, min(d.day, 28))


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("value", "count", "amount_usd"):
            if key in value:
                return _num(value[key])
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _norm(text: Any) -> str:
    return str(text or "").strip().lower().replace("-", "_").replace(" ", "_")


def _overlaps(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a and b) and (a in b or b in a)


def _latest(ev: Evidence, *predicates: str) -> Item | None:
    items = ev.get(*predicates)
    return items[-1] if items else None


def _sectors(ev: Evidence) -> tuple[list[str], list[Item]]:
    items = ev.get(fm.INDUSTRIES)
    latest = items[-1:] if items else []
    values = latest[0].value if latest else []
    return ([str(v) for v in values] if isinstance(values, list) else [str(values)]), latest


# --- thesis fit -----------------------------------------------------------------------

def thesis_match(ev: Evidence) -> RuleResult:
    """Matches per thesis dimension (sector, stage, geography); any exclusion → 0."""
    if not ev.thesis_points:
        return result(UNKNOWN, "No confirmed thesis to compare against", [])
    sectors, sector_items = _sectors(ev)
    desc = _latest(ev, fm.DESCRIPTION)
    text_items = sector_items + ([desc] if desc else [])
    haystack = " ".join(sectors + ([str(desc.value)] if desc else [])).lower()
    for point in ev.thesis("exclusion"):
        terms = [t.strip().lower() for t in str(point.get("value") or "").split(",")]
        hit = next((t for t in terms if t and t in haystack), None)
        if hit:
            return result(0, f"Thesis exclusion matched: {hit}", text_items, exclusion=hit)

    parts: list[float] = []
    reasons: list[str] = []
    used: list[Item] = []
    bonus = 0.0
    bonuses = {**ev.params.get("trend_bonus", {}), **ev.params.get("partner_lens", {})}

    sector_points = ev.thesis("sectors")
    if sector_points and sectors:
        value = sector_points[0].get("value") or {}
        top = value.get("top_sectors") or list(value.get("shares", {}))
        known = list(value.get("shares", {})) or top
        match = next((t for t in top for s in sectors if _overlaps(s, t)), None)
        near = match or next((t for t in known for s in sectors if _overlaps(s, t)), None)
        parts.append(100 if match else 60 if near else 0)
        reasons.append(f"sector {'matches ' + near if near else 'outside thesis'}")
        used += sector_items
        bonus += sum(b for k, b in bonuses.items() for s in sectors if _overlaps(s, k))

    stage_points = ev.thesis("stage")
    stage = _latest(ev, fm.LAST_ROUND_TYPE)
    if stage_points and stage:
        shares = stage_points[0].get("value") or {}
        fit = any(_norm(k) == _norm(stage.value) for k in shares)
        parts.append(100 if fit else 30)
        reasons.append(f"stage {stage.value} {'in' if fit else 'outside'} thesis")
        used.append(stage)
        bonus += sum(b for k, b in bonuses.items() if _norm(k) == _norm(stage.value))

    geo_points = ev.thesis("geography")
    country = _latest(ev, fm.HQ_COUNTRY)
    if geo_points and country:
        countries = (geo_points[0].get("value") or {}).get("countries", {})
        fit = any(_overlaps(k, country.value) for k in countries)
        parts.append(100 if fit else 0)
        reasons.append(f"HQ {country.value} {'in' if fit else 'outside'} thesis geography")
        used.append(country)

    if not parts:
        return result(UNKNOWN, "No sector, stage or geography data to match the thesis", [])
    score = statistics.fmean(parts) + bonus * 100
    return result(score, "; ".join(reasons) + (" (+trend/partner bonus)" if bonus else ""), used)


# --- team -----------------------------------------------------------------------------

def _job_years(job: Any, as_of: date) -> float:
    start = _date(job.get("start")) if isinstance(job, dict) else None
    if not start:
        return 0.0
    end = min(_date(job.get("end")) or as_of, as_of)
    return max((end - start).days / 365.25, 0.0)


def founder_years(ev: Evidence, person: str) -> tuple[float, list[Item]]:
    jobs = ev.get(fm.EMPLOYMENT, subject=person)
    return sum(_job_years(j.value, ev.as_of) for j in jobs), jobs


def _has(text: Any, words: tuple[str, ...]) -> bool:
    lower = str(text or "").lower()
    return any(w in lower for w in words)


def team_signals(ev: Evidence) -> RuleResult:
    """Points per founder signal: experience years, prior founding, technical depth, a
    team of founders. Pedigree only counts when `use_pedigree` is on."""
    founders = ev.founders()
    if not founders:
        return result(UNKNOWN, "No founder career history", [])
    score, reasons, used = 20.0, [], []
    best_years = 0.0
    for person in founders:
        years, jobs = founder_years(ev, person)
        best_years = max(best_years, years)
        if years:
            used += jobs
        prior = [j for j in jobs if _has(j.value.get("title"), ("founder",))
                 and _date(j.value.get("end"))]
        if prior:
            score += 25 if ev.params.get("founder_market_fit") else 20
            reasons.append("a founder has founded before")
            used += prior
        titles = jobs + ev.get(fm.CURRENT_TITLE, subject=person)
        tech = [t for t in titles
                if _has(t.value.get("title") if isinstance(t.value, dict) else t.value,
                        TECH_TITLE_WORDS)]
        if tech:
            score += 10
            used += tech[:1]
        if ev.params.get("use_pedigree"):
            schools = tuple(ev.params.get("pedigree_schools", DEFAULT_PEDIGREE_SCHOOLS))
            firms = tuple(ev.params.get("pedigree_companies", DEFAULT_PEDIGREE_COMPANIES))
            pedigree = [e for e in ev.get(fm.EDUCATION, subject=person)
                        if _has(e.value.get("school"), schools)]
            pedigree += [j for j in jobs if _has(j.value.get("company_name"), firms)]
            if pedigree:
                score += 10
                reasons.append("pedigree")
                used += pedigree
    if not used:
        return result(UNKNOWN, "Founders found but no dated career history", [])
    min_years = float(ev.params.get("domain_years", 5))
    score += 30 if best_years >= min_years else 15 if best_years >= 2 else 0
    reasons.insert(0, f"top founder has {best_years:.1f} years of experience")
    if len(founders) >= 2:
        score += 10
        reasons.append(f"{len(founders)} founders")
    return result(score, "; ".join(reasons), used)


# --- traction -------------------------------------------------------------------------

def headcount_change(ev: Evidence, window_months: int) -> tuple[float, Item, Item] | None:
    """Growth between the last point at/before the window start (else the first in the
    window) and the latest point. None when fewer than two dated points."""
    points = [p for p in ev.get(fm.HEADCOUNT_AT) if p.as_of and _num(p.value)]
    if len(points) < 2:
        return None
    start = months_before(ev.as_of, window_months)
    before = [p for p in points if p.as_of and p.as_of <= start]
    first = before[-1] if before else points[0]
    last = points[-1]
    if first is last or not _num(first.value):
        return None
    return (_num(last.value) or 0) / (_num(first.value) or 1) - 1, first, last


def growth_signals(ev: Evidence) -> RuleResult:
    """Headcount growth over the window against a benchmark (default +30% per window),
    plus hiring; for early-stage profiles, size vs the median headcount at entry."""
    window = int(ev.params.get("window_months", 6))
    benchmark = float(ev.params.get("growth_benchmark", 0.30))
    parts: list[float] = []
    reasons: list[str] = []
    used: list[Item] = []
    change = headcount_change(ev, window)
    if change:
        growth, first, last = change
        parts.append(50 + 25 * growth / benchmark)
        reasons.append(f"headcount {_num(first.value):g} → {_num(last.value):g} "
                       f"({growth:+.0%}) since {first.as_of}")
        used += [first, last]
    if ev.params.get("benchmark") == "median_headcount_at_entry":
        entry = ev.thesis("entry_profile")
        median = (entry[0].get("value") or {}).get("median_headcount") if entry else None
        latest = _latest(ev, fm.HEADCOUNT_AT, fm.HEADCOUNT_TOTAL)
        if median and latest and _num(latest.value):
            parts.append(50 * (_num(latest.value) or 0) / float(median))
            reasons.append(f"headcount {_num(latest.value):g} vs {median:g} median at entry")
            used.append(latest)
    if not parts:
        return result(UNKNOWN, "Fewer than two dated headcount points", [])
    since = months_before(ev.as_of, window)
    roles = [r for r in ev.get(OPEN_ROLES)
             if (r.as_of or _date(r.value.get("posted_at")) or ev.as_of) >= since]
    if roles:
        reasons.append(f"{len(roles)} open roles")
        used += roles
    return result(statistics.fmean(parts) + min(10, 2 * len(roles)), "; ".join(reasons), used)


# --- funding --------------------------------------------------------------------------

def funding_stage_fit(ev: Evidence) -> RuleResult:
    """Stage vs the thesis, size vs the check-size range, a recent raise (timing) and
    verified grants."""
    stage = _latest(ev, fm.LAST_ROUND_TYPE)
    rounds = ev.get(fm.FUNDING_ROUND)
    total = _latest(ev, fm.FUNDING_TOTAL_USD)
    grants = ev.get(GRANT)
    if not (stage or rounds or total or grants):
        return result(UNKNOWN, "No funding history or grants found", [])
    score, reasons, used = 0.0, [], []
    stage_name = stage.value if stage else (rounds[-1].value.get("round_type") if rounds else None)
    stage_points = ev.thesis("stage")
    if stage_name and stage_points:
        fit = any(_norm(k) == _norm(stage_name) for k in stage_points[0].get("value") or {})
        score += 50 if fit else 20
        reasons.append(f"{stage_name} {'fits' if fit else 'outside'} thesis stages")
    else:
        score += 35
    used += [i for i in (stage, total) if i]
    recent_months = int(ev.params.get("recent_months", 12))
    recent = [r for r in rounds if r.as_of and r.as_of >= months_before(ev.as_of, recent_months)]
    if recent:
        score += 25
        reasons.append(f"raised {recent[-1].value.get('round_type') or 'a round'} on "
                       f"{recent[-1].as_of}")
        used += recent
    check = ev.thesis("check_size")
    max_usd = (check[0].get("value") or {}).get("max_usd") if check else None
    amount = _num(rounds[-1].value.get("amount_usd")) if rounds else None
    if max_usd and amount and amount > 3 * float(max_usd):
        score -= 20
        reasons.append("last round far above the thesis check size")
        used.append(rounds[-1])
    if grants:
        score += 25
        reasons.append(f"{len(grants)} grant(s)")
        used += grants
    return result(score, "; ".join(reasons) or "funding data present", used)


# --- market ---------------------------------------------------------------------------

def market_signals(ev: Evidence) -> RuleResult:
    """Crowding (known competitors) plus an optional sector-growth table in params."""
    comp = _latest(ev, fm.COMPETITORS)
    if not comp:
        return result(UNKNOWN, "No competitor data", [])
    n = len(comp.value) if isinstance(comp.value, list) else 0
    crowd = ev.params.get("crowding", [3, 10])
    score = 80.0 if n <= crowd[0] else 60.0 if n <= crowd[1] else 40.0
    reason = f"{n} known competitors"
    sectors, items = _sectors(ev)
    growth = ev.params.get("sector_growth", {})
    boost = max((float(g) for k, g in growth.items() for s in sectors if _overlaps(s, k)),
                default=None)
    if boost is not None:
        score += 20 * boost
        reason += f"; sector growth {boost:+.0%}"
    return result(score, reason, [comp] + (items if boost is not None else []))


# --- momentum -------------------------------------------------------------------------

def recent_events(ev: Evidence) -> RuleResult:
    """Count and recency of dated events (news, rounds, grants) within the window."""
    events = [e for e in ev.get(fm.NEWS_ITEM, fm.FUNDING_ROUND, GRANT) if e.as_of]
    if not ev.get(fm.NEWS_ITEM) and not events:
        return result(UNKNOWN, "No news or dated events", [])
    window = int(ev.params.get("window_months", 6))
    since = months_before(ev.as_of, window)
    recent = [e for e in events if e.as_of and e.as_of >= since]
    if not recent:
        return result(20, f"No events in the last {window} months", [])
    last = max(e.as_of for e in recent if e.as_of)
    fresh = 15 if (ev.as_of - last).days <= 60 else 0
    return result(30 + 15 * len(recent) + fresh,
                  f"{len(recent)} events in the last {window} months, latest {last}", recent)


# --- optional criteria ----------------------------------------------------------------

def technical_depth(ev: Evidence) -> RuleResult:
    """Founders' engineering/research history and education, and the engineering share
    of headcount or open roles."""
    parts: list[float] = []
    reasons: list[str] = []
    used: list[Item] = []
    for person in ev.founders():
        jobs = [j for j in ev.get(fm.EMPLOYMENT, subject=person)
                if _has(j.value.get("title"), TECH_TITLE_WORDS)]
        years = sum(_job_years(j.value, ev.as_of) for j in jobs)
        edu = [e for e in ev.get(fm.EDUCATION, subject=person)
               if _has(f"{e.value.get('field')} {e.value.get('degree')}", TECH_FIELD_WORDS)]
        if jobs or edu:
            parts.append(min(100, 40 + 10 * years + (20 if edu else 0)))
            used += jobs + edu
    if parts:
        reasons.append("technical founder history")
    func = _latest(ev, fm.HEADCOUNT_BY_FUNCTION)
    roles = ev.get(OPEN_ROLES)
    share = None
    if func and isinstance(func.value, dict) and sum(func.value.values()):
        eng = sum(v for k, v in func.value.items() if _has(k, ("engineer", "research", "it")))
        share = eng / sum(func.value.values())
        used.append(func)
    elif roles:
        share = sum(_has(r.value.get("function"), ("engineer", "research")) for r in roles) / len(
            roles)
        used += roles
    if share is not None:
        parts.append(min(100, share * 200))
        reasons.append(f"{share:.0%} engineering")
    if not parts:
        return result(UNKNOWN, "No technical history or function mix", [])
    return result(statistics.fmean(parts), "; ".join(reasons), used)


def capital_efficiency(ev: Evidence) -> RuleResult:
    """Total raised per employee against a stage benchmark (default $100k per head)."""
    total = _latest(ev, fm.FUNDING_TOTAL_USD)
    heads = _latest(ev, fm.HEADCOUNT_AT, fm.HEADCOUNT_TOTAL)
    raised, count = (_num(total.value) if total else None), (_num(heads.value) if heads else None)
    if not raised or not count:
        return result(UNKNOWN, "Needs both total raised and headcount", [])
    benchmark = float(ev.params.get("usd_per_head", 100_000))
    per_head = raised / count
    return result(75 * benchmark / per_head, f"${per_head:,.0f} raised per employee "
                  f"(benchmark ${benchmark:,.0f})", [total, heads] if total and heads else [])


Rule = Callable[[Evidence], RuleResult]
RULES: dict[str, Rule] = {
    "thesis_match": thesis_match,
    "team_signals": team_signals,
    "growth_signals": growth_signals,
    "funding_stage_fit": funding_stage_fit,
    "market_signals": market_signals,
    "recent_events": recent_events,
    "technical_depth": technical_depth,
    "capital_efficiency": capital_efficiency,
}
# which claim predicates each rule covers (contradicted claims are penalised there)
RULE_PREDICATES: dict[str, frozenset[str]] = {
    "thesis_match": frozenset({fm.INDUSTRIES, fm.HQ_COUNTRY, fm.DESCRIPTION}),
    "team_signals": frozenset({fm.EMPLOYMENT, fm.EDUCATION, fm.CURRENT_TITLE, fm.FOUNDER}),
    "growth_signals": frozenset({fm.HEADCOUNT_AT, fm.HEADCOUNT_TOTAL, OPEN_ROLES,
                                 fm.WEB_TRAFFIC_MONTHLY}),
    "funding_stage_fit": frozenset({fm.FUNDING_ROUND, fm.FUNDING_TOTAL_USD,
                                    fm.LAST_ROUND_TYPE, GRANT}),
    "market_signals": frozenset({fm.COMPETITORS}),
    "recent_events": frozenset({fm.NEWS_ITEM}),
    "technical_depth": frozenset({fm.HEADCOUNT_BY_FUNCTION}),
    "capital_efficiency": frozenset(),
}
# what would settle each criterion when it is unknown
GAP_DATA: dict[str, str] = {
    "thesis_match": "the company's sector, stage and HQ country (or a confirmed thesis)",
    "team_signals": "founders' dated career history (LinkedIn or a team page)",
    "growth_signals": "headcount at two dates at least a few months apart",
    "funding_stage_fit": "funding history (rounds, amounts) or grant letters",
    "market_signals": "a competitor list",
    "recent_events": "dated news, launches or announcements",
    "technical_depth": "founders' engineering history or the team's function mix",
    "capital_efficiency": "total raised and current headcount",
}
