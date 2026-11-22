"""The scoring engine: run each profile criterion's rule and combine them. Pure.

- Unknown criteria are left out of the weighted score and listed; completeness is the
  share of criteria weight that is not unknown.
- Evidence weight: a fact counts by its source tier (`profile.source_tiers`), a verified
  claim 1.0, any other claim `self_reported_weight`. A criterion's evidence weight is
  the mean over the items its rule used; below 1 it pulls the score towards neutral (50).
- Each contradicted claim on a criterion's predicates costs `contradiction_penalty`
  points (thresholds, default 15) and raises a red flag (see `signals`).
"""

from dataclasses import asdict, dataclass, field, replace
from typing import Any

from app.models.enums import VerificationResult
from app.services.onboarding.profile import load_rules
from app.services.scoring.rules import RULE_PREDICATES, RULES, UNKNOWN, Evidence, Item, Score

NEUTRAL = 50.0
DEFAULT_PENALTY = 15.0


@dataclass(frozen=True)
class Profile:
    criteria: list[dict[str, Any]]
    thresholds: dict[str, Any]
    self_reported_weight: float = 0.5
    source_tiers: dict[str, float] = field(
        default_factory=lambda: {"A": 1.0, "B": 0.8, "C": 0.5})
    version: int = 0  # 0 = the generic fallback, not a stored profile

    @classmethod
    def generic(cls) -> "Profile":
        g = load_rules()["generic"]
        return cls(g["criteria"], g["thresholds"], g["self_reported_weight"], g["source_tiers"])


@dataclass(frozen=True)
class CriterionResult:
    key: str
    rule: str
    weight: float
    score: Score
    reason: str
    fact_ids: tuple[int, ...] = ()
    claim_ids: tuple[str, ...] = ()
    evidence_weight: float | None = None
    contradicted_claim_ids: tuple[str, ...] = ()
    self_reported_only: bool = False


@dataclass(frozen=True)
class Breakdown:
    score: float | None
    completeness: float
    criteria: tuple[CriterionResult, ...]
    exclusion: str | None = None

    @property
    def unknown(self) -> list[str]:
        return [c.key for c in self.criteria if c.score == UNKNOWN]

    def to_json(self) -> list[dict[str, Any]]:
        return [asdict(c) | {"fact_ids": list(c.fact_ids), "claim_ids": list(c.claim_ids),
                             "contradicted_claim_ids": list(c.contradicted_claim_ids)}
                for c in self.criteria]


def item_weight(item: Item, profile: Profile) -> float:
    if not item.is_claim:
        return float(profile.source_tiers.get(item.tier or "A", 1.0))
    if item.verification == VerificationResult.verified:
        return 1.0
    return float(profile.self_reported_weight)


def _criterion(spec: dict[str, Any], evidence: Evidence, profile: Profile
               ) -> tuple[CriterionResult, str | None]:
    key, rule_name, weight = spec["key"], spec["rule"], float(spec["weight"])
    rule = RULES.get(rule_name)
    if rule is None:
        return CriterionResult(key, rule_name, weight, UNKNOWN, f"Unknown rule {rule_name}"), None
    ev = replace(evidence, params=spec.get("params") or {})
    res = rule(ev)
    bad = ev.contradicted(RULE_PREDICATES.get(rule_name, frozenset()))
    bad_ids = tuple(sorted(str(i.id) for i in bad))
    if res.score == UNKNOWN:
        return CriterionResult(key, rule_name, weight, UNKNOWN, res.reason, res.fact_ids,
                               tuple(sorted(set(res.claim_ids) | set(bad_ids))),
                               contradicted_claim_ids=bad_ids), None
    used_ids = {str(i) for i in res.fact_ids} | set(res.claim_ids)
    used = [i for i in ev.items if str(i.id) in used_ids]
    w = sum(item_weight(i, profile) for i in used) / len(used) if used else 1.0
    score = res.score if res.exclusion else NEUTRAL + (res.score - NEUTRAL) * w
    penalty = float(profile.thresholds.get("contradiction_penalty", DEFAULT_PENALTY))
    score = round(max(score - penalty * len(bad), 0.0), 1)
    reason = res.reason + (f"; {len(bad)} contradicted claim(s) −{penalty * len(bad):g}"
                           if bad else "")
    return CriterionResult(
        key, rule_name, weight, score, reason, res.fact_ids,
        tuple(sorted(set(res.claim_ids) | set(bad_ids))), round(w, 3), bad_ids,
        self_reported_only=bool(used) and all(
            i.is_claim and i.verification != VerificationResult.verified for i in used),
    ), res.exclusion


def score(evidence: Evidence, profile: Profile) -> Breakdown:
    """Same evidence and profile → same breakdown."""
    results, exclusion = [], None
    for spec in profile.criteria:
        res, excl = _criterion(spec, evidence, profile)
        results.append(res)
        exclusion = exclusion or excl
    total = sum(r.weight for r in results)
    known = [r for r in results if r.score != UNKNOWN]
    known_weight = sum(r.weight for r in known)
    weighted = (round(sum(r.weight * float(r.score) for r in known) / known_weight, 2)
                if known_weight else None)
    completeness = round(known_weight / total, 3) if total else 0.0
    return Breakdown(weighted, completeness, tuple(results), exclusion)
