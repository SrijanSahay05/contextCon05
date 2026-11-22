"""Scoring-profile derivation: rules from `app/profile_rules.json` over deals and the partner.

Pure. Every change from the generic profile is recorded as a derivation step with its
reason and the deal (or person source) ids behind it.
"""

import copy
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.models.enums import Confidence, ProfileOrigin
from app.services.onboarding.deals import parse_date
from app.services.onboarding.thesis import DealInput, ThesisResult

RULES_PATH = Path(__file__).resolve().parents[2] / "profile_rules.json"


def load_rules(path: Path = RULES_PATH) -> dict[str, Any]:
    rules: dict[str, Any] = json.loads(path.read_text())
    return rules


@dataclass
class PartnerProfile:
    engineering_years: float = 0.0
    was_founder: bool = False
    finance_background: bool = False
    past_sectors: list[str] = field(default_factory=list)
    championed_company_ids: list[str] = field(default_factory=list)
    evidence_id: str | None = None  # the person-enrich source id behind the career facts


@dataclass
class ProfileResult:
    origin: ProfileOrigin
    confidence: Confidence
    criteria: list[dict[str, Any]]
    thresholds: dict[str, Any]
    self_reported_weight: float
    source_tiers: dict[str, float]
    derivation: list[dict[str, Any]]


def _has_keyword(title: str, keywords: list[str]) -> bool:
    return any(re.search(r"\b" + re.escape(k), title) for k in keywords)


def partner_from_person(
    person_data: dict[str, Any], as_of: date, rules: dict[str, Any] | None = None,
) -> PartnerProfile:
    """Career facts from a Crustdata person-enrich `person_data` object."""
    keywords = (rules or load_rules())["title_keywords"]
    jobs = (person_data.get("experience") or {}).get("employment_details") or {}
    partner = PartnerProfile()
    sectors: set[str] = set()
    for job in (jobs.get("current") or []) + (jobs.get("past") or []):
        title = (job.get("title") or "").lower()
        start = parse_date(job.get("start_date"))
        end = parse_date(job.get("end_date")) or as_of
        years = max((end - start).days / 365.25, 0) if start else 0.0
        if _has_keyword(title, keywords["engineering"]):
            partner.engineering_years += years
        partner.was_founder |= _has_keyword(title, keywords["founder"])
        partner.finance_background |= _has_keyword(title, keywords["finance"])
        # response-shape guess: industry per role is not documented; read it if present
        industry = job.get("company_industry") or job.get("industry")
        if industry:
            sectors.add(str(industry))
    partner.engineering_years = round(partner.engineering_years, 1)
    partner.past_sectors = sorted(sectors)
    return partner


def _share(deals: list[DealInput], stages: list[str]) -> tuple[float, list[str]]:
    hits = [d.id for d in deals if d.round_type in stages]
    return (len(hits) / len(deals) if deals else 0.0), hits


def derive_profile(
    deals: list[DealInput],
    thesis: ThesisResult,
    partner: PartnerProfile,
    rules: dict[str, Any] | None = None,
) -> ProfileResult:
    rules = rules or load_rules()
    generic = copy.deepcopy(rules["generic"])
    criteria: dict[str, dict[str, Any]] = {c["key"]: c for c in generic["criteria"]}
    derivation: list[dict[str, Any]] = []
    all_ids = [d.id for d in deals]

    def result(origin: ProfileOrigin, confidence: Confidence) -> ProfileResult:
        return ProfileResult(
            origin, confidence, list(criteria.values()), generic["thresholds"],
            generic["self_reported_weight"], generic["source_tiers"], derivation,
        )

    if len(deals) < rules["min_deals"]:
        derivation.append({
            "target": "profile", "change": "generic weights",
            "reason": f"low confidence: generic profile ({len(deals)} deals in the window, "
                      f"fewer than {rules['min_deals']})",
            "evidence_ids": all_ids,
        })
        return result(ProfileOrigin.generic, Confidence.low)

    def adjust(changes: dict[str, float], reason: str, ids: list[str]) -> None:
        for key, delta in changes.items():
            before = criteria[key]["weight"]
            criteria[key]["weight"] = round(max(before + delta, 0.0), 4)
            derivation.append({
                "target": f"{key}.weight",
                "change": f"{before:.2f} → {criteria[key]['weight']:.2f}",
                "reason": reason, "evidence_ids": ids,
            })

    def set_param(key: str, param: str, value: Any, reason: str, ids: list[str]) -> None:
        criteria[key]["params"][param] = value
        derivation.append({"target": f"{key}.params.{param}", "change": f"set to {value}",
                           "reason": reason, "evidence_ids": ids})

    def add_criterion(spec: dict[str, Any], reason: str, ids: list[str]) -> None:
        taken = spec["weight"] / len(criteria)
        for c in criteria.values():
            c["weight"] = round(max(c["weight"] - taken, 0.0), 4)
        criteria[spec["key"]] = copy.deepcopy(spec)
        derivation.append({
            "target": spec["key"], "change": f"added at {spec['weight']:.2f}, "
            f"{taken:.3f} taken from each other criterion", "reason": reason,
            "evidence_ids": ids,
        })

    n = len(deals)
    early, early_ids = _share(deals, rules["early_stages"])
    later, later_ids = _share(deals, rules["later_stages"])
    rule = rules["early_heavy"]
    if early >= rule["min_share"]:
        reason = f"{len(early_ids)} of {n} deals were pre-seed or seed"
        adjust(rule["adjust"], reason, early_ids)
        for key, params in rule.get("params", {}).items():
            for param, value in params.items():
                set_param(key, param, value, reason, early_ids)
    rule = rules["later_heavy"]
    if later >= rule["min_share"]:
        adjust(rule["adjust"], f"{len(later_ids)} of {n} deals were Series A or later",
               later_ids)

    sectors = next((p for p in thesis.points if p["dimension"] == "sectors"), None)
    if sectors:
        shares = sectors["value"]["shares"]
        top = max(shares, key=shares.get)
        rule = rules["concentrated"]
        if shares[top] >= rule["min_top_share"]:
            ids = [d.id for d in deals if (d.sectors or ["unknown"])[0] == top]
            adjust(rule["adjust"], f"{len(ids)} of {n} deals were in {top}", ids)

    lead_known = [d for d in deals if d.led is not None]
    led_ids = [d.id for d in lead_known if d.led]
    rule = rules["lead_heavy"]
    if lead_known and len(led_ids) / len(lead_known) >= rule["min_lead_share"]:
        adjust(rule["adjust"], f"the firm led {len(led_ids)} of {len(lead_known)} deals",
               led_ids)

    trend = next((p for p in thesis.points if p["dimension"] == "trend"), None)
    rule = rules["trend"]
    rising = [s for s in (trend["value"]["shifts"] if trend else [])
              if s["direction"] == "rising" and len(s["deal_ids"]) >= rule["min_deals"]]
    if rising:
        set_param("thesis_fit", "trend_bonus", {s["key"]: rule["bonus"] for s in rising},
                  "rising in the last 6 months: " + ", ".join(s["key"] for s in rising),
                  sorted({i for s in rising for i in s["deal_ids"]}))

    rule = rules["partner_lens"]
    championed: dict[str, list[str]] = {}
    for d in deals:
        if d.championed:
            championed.setdefault((d.sectors or ["unknown"])[0], []).append(d.id)
    lens = {s: ids for s, ids in championed.items() if len(ids) >= rule["min_deals"]}
    if lens:
        set_param("thesis_fit", "partner_lens", {s: rule["bonus"] for s in lens},
                  "the partner championed deals in " + ", ".join(
                      f"{s} ({len(ids)})" for s, ids in lens.items()),
                  [i for ids in lens.values() for i in ids])

    career = [partner.evidence_id] if partner.evidence_id else []
    rule = rules["technical_partner"]
    if career and partner.engineering_years >= rule["min_years"]:
        add_criterion(rule["criterion"], f"the partner spent {partner.engineering_years:g} "
                      "years in engineering or research roles", career)
    if career and partner.was_founder:
        rule = rules["founder_partner"]
        set_param(rule["criterion"], rule["param"], True, "the partner was a founder", career)
    if career and partner.finance_background:
        add_criterion(rules["finance_partner"]["criterion"],
                      "the partner has a finance or banking background", career)

    total = sum(c["weight"] for c in criteria.values())
    if abs(total - 1) > 1e-9:
        for c in criteria.values():
            c["weight"] = round(c["weight"] / total, 4)
        derivation.append({
            "target": "weights", "change": f"re-normalised from {total:.2f} to 1",
            "reason": "adjusted weights must sum to 1",
            "evidence_ids": sorted({i for s in derivation for i in s["evidence_ids"]}),
        })
    return result(ProfileOrigin.derived, thesis.confidence)
