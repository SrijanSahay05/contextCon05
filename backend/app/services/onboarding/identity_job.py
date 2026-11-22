"""Job `onboarding_identity`: the firm's profile, then its candidate investor records."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.identity import Fund
from app.services.clients import clients_for_run
from app.services.jobs.registry import register
from app.services.jobs.steps import StepRunner, ensure_budget
from app.services.onboarding import firm
from app.services.onboarding.names import name_variants

SEARCH_LIMIT = 25
SEARCH_FIELDS = ["crustdata_company_id", "basic_info.name", "basic_info.primary_domain",
                 "funding.investors"]


def _fund_profile(db: Session, runner: StepRunner, fund: Fund) -> dict[str, Any]:
    ensure_budget(db, runner.run_id)
    crust = clients_for_run(runner.run_id).crustdata
    body: dict[str, Any] = (
        {"crustdata_company_ids": [fund.crustdata_company_id]}
        if fund.crustdata_company_id is not None else {"names": [fund.name]}
    )
    result = crust.company_enrich({**body, "fields": ["basic_info"]})
    matches = [m for item in result.data or [] for m in item.get("matches") or []]
    info = (matches[0].get("company_data") or {}).get("basic_info") or {} if matches else {}
    fund.name = info.get("name") or fund.name
    fund.domain = info.get("primary_domain") or fund.domain
    db.commit()
    return {"name": fund.name, "domain": fund.domain, "description": info.get("description"),
            "source_id": str(result.source_id), "matched": bool(matches)}


def _alias_candidates(db: Session, runner: StepRunner, profile: dict[str, Any]) -> dict[str, Any]:
    crust = clients_for_run(runner.run_id).crustdata
    variants = name_variants(profile["name"], profile.get("domain"))
    responses = []
    for variant in variants:
        ensure_budget(db, runner.run_id)
        responses.append(crust.company_search({
            "filters": {"field": "funding.investors", "type": "(.)", "value": variant},
            "limit": SEARCH_LIMIT,
            "fields": SEARCH_FIELDS,
        }).data)
    searched = firm.search_companies(responses)
    ids = firm.pick_for_enrich(searched, variants)
    enriched: list[tuple[dict[str, Any], str]] = []
    if ids:
        ensure_budget(db, runner.run_id)
        result = crust.company_enrich(
            {"crustdata_company_ids": ids, "fields": ["basic_info", "funding"]})
        enriched = [
            (m["company_data"], str(result.source_id))
            for item in result.data or [] for m in (item.get("matches") or [])[:1]
            if m.get("company_data")
        ]
    candidates = firm.group_candidates(enriched, searched, variants, profile["name"])
    return {"variants": variants, "searched": len(searched), "enriched": len(enriched),
            "candidates": candidates}


@register("onboarding_identity")
def onboarding_identity(db: Session, runner: StepRunner, payload: dict[str, Any]) -> None:
    fund = db.get(Fund, uuid.UUID(payload["fund_id"]))
    if fund is None:
        raise ValueError(f"fund {payload['fund_id']} is gone")
    runner.step("identity", lambda: {
        "investor_id": payload["investor_id"],
        "employer": payload.get("employer"),
        "recent_move": payload.get("recent_move", False),
    })
    profile = runner.step("fund_profile", lambda: _fund_profile(db, runner, fund))
    runner.step("alias_candidates", lambda: _alias_candidates(db, runner, profile))
