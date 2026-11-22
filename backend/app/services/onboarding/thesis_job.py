"""`onboarding_thesis` job: portfolio → deals → partner → thesis → scoring profile.

Payload: `{investor_id, fund_id, as_of?}`. Every step is resumable; re-running the job
re-uses existing deal rows, so deals are never duplicated.
"""

import re
import uuid
from dataclasses import asdict
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.entities import Company
from app.models.enums import Confidence
from app.models.identity import FundAlias, Investor, InvestorPostLink
from app.models.onboarding import Deal
from app.repositories import profiles, theses
from app.services.clients import clients_for_run
from app.services.jobs.registry import register
from app.services.jobs.steps import StepRunner, ensure_budget
from app.services.onboarding.deals import deals_from_company, entry_profile, parse_date
from app.services.onboarding.profile import PartnerProfile, derive_profile, partner_from_person
from app.services.onboarding.thesis import DealInput, infer_thesis, months_before, summary_sentence

WINDOW_MONTHS = 18
WIDE_WINDOW_MONTHS = 36
MAX_COMPANIES = 30
ENRICH_BATCH = 25
SEARCH_LIMIT = 25
POST_KEYWORDS = ["backed", "invested", "investment", "welcome to the portfolio", "led the round",
                 "leading the round", "excited to partner"]
ENRICH_FIELDS = ["basic_info", "headcount", "funding", "taxonomy", "locations"]


def _company_data(entry: dict[str, Any]) -> dict[str, Any] | None:
    matches = entry.get("matches") or []
    data = matches[0].get("company_data") if matches else None
    return data if isinstance(data, dict) else None


@register("onboarding_thesis")
def onboarding_thesis(db: Session, runner: StepRunner, payload: dict[str, Any]) -> None:
    investor_id = uuid.UUID(payload["investor_id"])
    fund_id = uuid.UUID(payload["fund_id"])
    as_of = parse_date(payload.get("as_of")) or date.today()
    start = months_before(as_of, WIDE_WINDOW_MONTHS)
    crust = clients_for_run(runner.run_id).crustdata
    aliases = db.scalars(
        select(FundAlias).where(FundAlias.fund_id == fund_id, FundAlias.confirmed_at.is_not(None))
    ).all()
    names = {a.canonical_name for a in aliases}
    permalinks = {a.permalink for a in aliases}

    def portfolio() -> list[int]:
        ids: dict[int, None] = {}
        for name in sorted(names):
            ensure_budget(db, runner.run_id)
            found = crust.company_search({
                "filters": {"op": "and", "conditions": [
                    {"field": "funding.investors", "type": "in", "value": [name]},
                    {"field": "funding.last_fundraise_date", "type": "=>",
                     "value": start.isoformat()},
                ]},
                "fields": ["basic_info"],
                "limit": SEARCH_LIMIT,
            })
            for company in (found.data or {}).get("companies") or []:
                ids.setdefault(int(company["crustdata_company_id"]))
        return list(ids)[:MAX_COMPANIES]

    company_ids = runner.step("portfolio", portfolio)

    def collect_deals() -> dict[str, Any]:
        deals: list[dict[str, Any]] = []
        flagged: list[dict[str, Any]] = []
        for i in range(0, len(company_ids), ENRICH_BATCH):
            ensure_budget(db, runner.run_id)
            enriched = crust.company_enrich({
                "crustdata_company_ids": company_ids[i:i + ENRICH_BATCH],
                "fields": ENRICH_FIELDS,
            })
            for entry in enriched.data or []:
                data = _company_data(entry)
                if data is None:
                    continue
                drafts = deals_from_company(data, names, permalinks, (start, as_of))
                if not drafts:
                    continue
                company = _upsert_company(db, data)
                for draft in drafts:
                    if draft.flag:
                        flagged.append({"company_id": str(company.id), "flag": draft.flag,
                                        "evidence": draft.match_evidence})
                        continue
                    assert draft.round_date is not None
                    deal = _upsert_deal(db, fund_id, company.id, draft.__dict__,
                                        enriched.source_id)
                    profile = entry_profile(data, draft.round_date)
                    deals.append(asdict(DealInput(
                        id=str(deal.id), company_id=str(company.id),
                        round_date=draft.round_date, round_type=draft.round_type,
                        amount_usd=draft.amount_usd, led=draft.led, sectors=profile.sectors,
                        country=profile.country, city=profile.city,
                        age_years=profile.age_years, headcount=profile.headcount,
                    )) | {"round_date": draft.round_date.isoformat(), "name": company.name})
        db.commit()
        return {"deals": deals, "flagged": flagged}

    found = runner.step("deals", collect_deals)

    def partner() -> dict[str, Any]:
        investor = db.get(Investor, investor_id)
        if investor is None or not investor.linkedin_url:
            return asdict(PartnerProfile())
        ensure_budget(db, runner.run_id)
        person = crust.person_enrich({
            "professional_network_profile_urls": [investor.linkedin_url],
            "fields": ["basic_profile", "experience"],
        })
        matches = (person.data or [{}])[0].get("matches") or []
        profile = (
            partner_from_person(matches[0].get("person_data") or {}, as_of)
            if matches else PartnerProfile()
        )
        profile.evidence_id = str(person.source_id) if matches else None

        author = (
            {"field": "actor.crustdata_entity_id", "type": "=",
             "value": investor.crustdata_person_id}
            if investor.crustdata_person_id
            else {"field": "actor.professional_network_url", "type": "=",
                  "value": investor.linkedin_url}
        )
        ensure_budget(db, runner.run_id)
        posts = crust.social_post_search({
            "filters": {"op": "and", "conditions": [
                author,
                {"op": "or", "conditions": [
                    {"field": "text", "type": "[.]", "value": kw} for kw in POST_KEYWORDS
                ]},
                {"field": "date_posted", "type": "=>", "value": start.isoformat()},
            ]},
            "fields": ["share_url", "text", "actor", "date_posted"],
            "limit": 50,
        })
        companies = {d["company_id"]: d["name"] for d in found["deals"]}
        championed: set[str] = set()
        for post in (posts.data or {}).get("posts") or []:
            text = post.get("text") or ""
            for company_id, name in companies.items():
                if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
                    championed.add(company_id)
        for company_id in championed:
            db.execute(insert(InvestorPostLink).values(
                investor_id=investor_id, company_id=uuid.UUID(company_id),
                source_id=posts.source_id,
            ).on_conflict_do_nothing())
            for deal in db.scalars(select(Deal).where(
                Deal.fund_id == fund_id, Deal.company_id == uuid.UUID(company_id)
            )):
                deal.championed_by_investor_id = investor_id
        db.commit()
        profile.championed_company_ids = sorted(championed)
        return asdict(profile)

    partner_data = runner.step("partner", partner)
    partner_profile = PartnerProfile(**partner_data)
    deal_inputs = [
        DealInput(**{k: v for k, v in d.items() if k != "name"}
                  | {"round_date": date.fromisoformat(d["round_date"]),
                     "championed": d["company_id"] in partner_profile.championed_company_ids})
        for d in found["deals"]
    ]

    def thesis() -> dict[str, Any]:
        months = WINDOW_MONTHS
        result = infer_thesis(deal_inputs, as_of, months, partner_profile.past_sectors)
        if result.confidence == Confidence.low:
            months = WIDE_WINDOW_MONTHS  # thin evidence: widen from already-enriched deals
            result = infer_thesis(deal_inputs, as_of, months, partner_profile.past_sectors)
        row = theses.create(
            db, investor_id=investor_id, fund_id=fund_id,
            window=(result.window_start, result.window_end), confidence=result.confidence,
            points=result.points, summary=summary_sentence(result),
        )
        db.commit()
        return {"thesis_id": str(row.id), "window_months": months}

    thesis_out = runner.step("thesis", thesis)

    def profile() -> dict[str, Any]:
        result = infer_thesis(deal_inputs, as_of, thesis_out["window_months"],
                              partner_profile.past_sectors)
        window_deals = [d for d in deal_inputs if d.id in set(result.deal_ids)]
        derived = derive_profile(window_deals, result, partner_profile)
        row = profiles.create(
            db, investor_id=investor_id, thesis_id=uuid.UUID(thesis_out["thesis_id"]),
            origin=derived.origin, confidence=derived.confidence, criteria=derived.criteria,
            thresholds=derived.thresholds, self_reported_weight=derived.self_reported_weight,
            source_tiers=derived.source_tiers, derivation=derived.derivation,
        )
        db.commit()
        return {"profile_id": str(row.id)}

    runner.step("profile", profile)


def _upsert_company(db: Session, data: dict[str, Any]) -> Company:
    basic = data.get("basic_info") or {}
    crust_id = int(data["crustdata_company_id"])
    name = basic.get("name") or str(crust_id)
    db.execute(
        insert(Company)
        .values(crustdata_company_id=crust_id, name=name, domain=basic.get("primary_domain"))
        .on_conflict_do_update(index_elements=["crustdata_company_id"],
                               set_={"name": name, "domain": basic.get("primary_domain")})
    )
    company = db.scalar(select(Company).where(Company.crustdata_company_id == crust_id))
    assert company is not None
    return company


def _upsert_deal(
    db: Session, fund_id: uuid.UUID, company_id: uuid.UUID, draft: dict[str, Any],
    source_id: uuid.UUID,
) -> Deal:
    existing = db.scalar(select(Deal).where(
        Deal.fund_id == fund_id, Deal.company_id == company_id,
        Deal.round_date.is_not_distinct_from(draft["round_date"]),
        Deal.round_type.is_not_distinct_from(draft["round_type"]),
    ))
    if existing is not None:
        return existing
    deal = Deal(
        fund_id=fund_id, company_id=company_id, round_date=draft["round_date"],
        round_type=draft["round_type"], amount_usd=draft["amount_usd"], led=draft["led"],
        match_rule=draft["match_rule"], match_evidence=draft["match_evidence"],
        source_id=source_id,
    )
    db.add(deal)
    db.flush()
    return deal
