"""Check one founder claim against independent facts (pure: no I/O, no LLM).

Claims use the fact predicate names (`facts_mapper`). Numbers count as verified within
`TOLERANCE_PCT` when the dates are within `TOLERANCE_DAYS`; a grant is verified only by a
web-quoted `grant` fact; revenue-like numbers have no public source (`self_reported`).
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.models.enums import VerificationResult as R
from app.services.evidence import facts_mapper as fm
from app.services.scoring.rules import GRANT, Item

TOLERANCE_PCT = 0.15
TOLERANCE_DAYS = 60

# claim predicate → fact predicates it is compared with ("headcount" is the scoring alias)
NUMERIC = {
    fm.HEADCOUNT_TOTAL: (fm.HEADCOUNT_TOTAL, fm.HEADCOUNT_AT),
    "headcount": (fm.HEADCOUNT_TOTAL, fm.HEADCOUNT_AT),
    fm.FUNDING_TOTAL_USD: (fm.FUNDING_TOTAL_USD,),
    "funding_total": (fm.FUNDING_TOTAL_USD,),
}
SELF_REPORTED = frozenset({"revenue_usd", "arr_usd", "customers", "burn_usd"})
# background predicates: the fields compared, primary field first
BACKGROUND = {
    fm.FOUNDER: ("name", "title"),
    fm.EMPLOYMENT: ("company_name", "title"),
    fm.EDUCATION: ("school", "degree", "field"),
}


@dataclass(frozen=True)
class Tolerance:
    pct: float = TOLERANCE_PCT
    days: int = TOLERANCE_DAYS

    def as_json(self) -> dict[str, Any]:
        return {"pct": self.pct, "days": self.days}


Outcome = tuple[R, list[int], str]


def _num(value: Any) -> float | None:
    if isinstance(value, dict):
        value = next((value[k] for k in ("value", "count", "amount_usd") if k in value), None)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gap(a: date | None, b: date | None) -> int:
    return abs((a - b).days) if a and b else 0


def _text(value: Any) -> str:
    return str(value or "").strip().casefold()


def _contains(a: Any, b: Any) -> bool:
    a, b = _text(a), _text(b)
    return bool(a and b) and (a in b or b in a)


def _ids(facts: list[Item]) -> list[int]:
    return [int(f.id) for f in facts]


def _numeric(claim: Item, facts: list[Item], tol: Tolerance) -> Outcome:
    claimed = _num(claim.value)
    preds = NUMERIC[claim.predicate]
    usable = [f for f in facts if f.predicate in preds and _num(f.value) is not None]
    if claimed is None or not usable:
        return R.unverifiable, [], f"No independent {preds[0]} to compare with"
    near = [f for f in usable if _gap(claim.as_of, f.as_of) <= tol.days]
    if not near:
        return R.unverifiable, [], (f"No {preds[0]} within {tol.days} days of "
                                    f"{claim.as_of}")
    # nearest date wins; dated facts beat undated ones, then the latest
    fact = min(near, key=lambda f: (f.as_of is None, _gap(claim.as_of, f.as_of),
                                    -(f.as_of or date.min).toordinal()))
    actual = _num(fact.value) or 0.0
    diff = (claimed - actual) / actual if actual else float("inf")
    when = f" on {fact.as_of}" if fact.as_of else ""
    note = (f"Claim says {claimed:g}{f' ({claim.as_of})' if claim.as_of else ''}; "
            f"{fact.predicate} was {actual:g}{when} ({diff:+.0%})")
    result = R.verified if abs(diff) <= tol.pct else R.contradicted
    return result, [int(fact.id)], note


def _round(claim: Item, facts: list[Item], tol: Tolerance) -> Outcome:
    value = claim.value if isinstance(claim.value, dict) else {"round_type": claim.value}
    kind = value.get("round_type")
    same = [f for f in facts if f.predicate == fm.FUNDING_ROUND and isinstance(f.value, dict)
            and (not kind or _text(f.value.get("round_type")) == _text(kind))]
    if not same:
        return R.unverifiable, [], f"No funding round of type {kind or 'any'} on record"
    amount = _num(value.get("amount_usd"))
    for f in same:
        actual = _num(f.value.get("amount_usd"))
        amount_ok = amount is None or actual is None or abs(amount - actual) <= tol.pct * actual
        if amount_ok and _gap(claim.as_of, f.as_of) <= tol.days:
            return R.verified, [int(f.id)], f"Matches the {kind or 'funding'} round ({f.as_of})"
    found = ", ".join(f"{f.value.get('amount_usd')} on {f.as_of}" for f in same)
    return R.contradicted, _ids(same), (f"Claim says {kind or 'round'} {value.get('amount_usd')} "
                                        f"({claim.as_of}); on record: {found}")


def _last_round(claim: Item, facts: list[Item]) -> Outcome:
    same = [f for f in facts if f.predicate == fm.LAST_ROUND_TYPE]
    if not same:
        return R.unverifiable, [], "No last round type on record"
    fact = same[-1]
    # "Series C" and "series_c" are the same round
    if _round_key(fact.value) == _round_key(claim.value):
        return R.verified, [int(fact.id)], f"Last round on record is {fact.value}"
    return R.contradicted, [int(fact.id)], (f"Claim says {claim.value}; last round on record "
                                            f"is {fact.value}")


def _round_key(value: object) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _exact(claim: Item, facts: list[Item]) -> Outcome:
    """Single-valued company fields (year founded, HQ country): equal or not."""
    same = [f for f in facts if f.predicate == claim.predicate]
    if not same:
        return R.unverifiable, [], f"No {claim.predicate} on record"
    fact = same[-1]
    if _round_key(fact.value) == _round_key(claim.value):
        return R.verified, [int(fact.id)], f"{claim.predicate} on record is {fact.value}"
    return R.contradicted, [int(fact.id)], (f"Claim says {claim.value}; "
                                            f"{claim.predicate} on record is {fact.value}")


def _background(claim: Item, facts: list[Item]) -> Outcome:
    fields = BACKGROUND[claim.predicate]
    same = [f for f in facts if f.predicate == claim.predicate and isinstance(f.value, dict)]
    if not same:
        return R.unverifiable, [], f"No {claim.predicate} history on record"
    value = claim.value if isinstance(claim.value, dict) else {fields[0]: claim.value}
    wanted = {k: v for k, v in value.items() if k in fields and _text(v)}
    if not wanted:
        return R.unverifiable, [], f"Claim names no {'/'.join(fields)}"
    for f in same:
        if all(_contains(v, f.value.get(k)) for k, v in wanted.items()):
            return R.verified, [int(f.id)], f"Matches {claim.predicate}: {f.value}"
    return R.contradicted, _ids(same), (f"No {claim.predicate} on record matches "
                                        f"{', '.join(map(str, wanted.values()))}")


def _grant(claim: Item, facts: list[Item]) -> Outcome:
    value = claim.value if isinstance(claim.value, dict) else {"program": claim.value}
    # ingestion asks for `name`; web-verified grant facts store `program`
    program = value.get("program") or value.get("name")
    for f in facts:
        if f.predicate == GRANT and isinstance(f.value, dict) \
                and _contains(program, f.value.get("program")):
            return R.verified, [int(f.id)], f"Quoted on the web: {f.value.get('program')}"
    return R.unverifiable, [], f"No public record of the grant {program or ''}".rstrip()


def verify(claim: Item, facts: list[Item], tolerance: Tolerance = Tolerance()) -> Outcome:
    """(result, fact ids used, note) for one claim against the company's and founders' facts."""
    p = claim.predicate
    if p in SELF_REPORTED:
        return R.self_reported, [], "No public source for this figure"
    if p in NUMERIC:
        return _numeric(claim, facts, tolerance)
    if p == fm.FUNDING_ROUND:
        return _round(claim, facts, tolerance)
    if p == fm.LAST_ROUND_TYPE:
        return _last_round(claim, facts)
    if p in BACKGROUND:
        return _background(claim, facts)
    if p == GRANT:
        return _grant(claim, facts)
    if p in (fm.YEAR_FOUNDED, fm.HQ_COUNTRY):
        return _exact(claim, facts)
    return R.unverifiable, [], f"No independent source for {p}"
