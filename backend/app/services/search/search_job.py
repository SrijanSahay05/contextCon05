"""`search_run` job: discover → enrich → grants → candidates.

Payload: `{search_id, investor_id}`. Every step is resumable and idempotent. Scoring and
the final `search.status` are left to the steps the integrator appends.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import Company
from app.models.enums import SearchStatus
from app.models.search import Search
from app.repositories.candidates import get_or_create_candidate
from app.schemas.search import FilterSpec
from app.services.clients import clients_for_run
from app.services.jobs.registry import register
from app.services.jobs.steps import StepRunner, ensure_budget
from app.services.scoring.service import score_search
from app.services.search.concepts import gate
from app.services.search.discovery import discover, enrich, months_before
from app.services.search.grants import check_grants

DEFAULT_GRANT_MONTHS = 36


@register("search_run")
def search_run(db: Session, runner: StepRunner, payload: dict[str, Any]) -> None:
    search_id = uuid.UUID(payload["search_id"])
    search = db.get(Search, search_id)
    if search is None:
        raise ValueError(f"search {search_id} not found")
    spec = FilterSpec.model_validate(search.parsed_filters)
    as_of = search.as_of or date.today()
    clients = clients_for_run(runner.run_id)

    def budget() -> None:
        ensure_budget(db, runner.run_id)

    found = runner.step("discover", lambda: discover(clients, spec, as_of, budget))
    crust_ids = [c["crustdata_company_id"] for c in found["candidates"]]

    def run_enrich() -> dict[str, Any]:
        out = enrich(db, clients, crust_ids, budget)
        db.commit()
        return out

    enriched = runner.step("enrich", run_enrich)
    # discovery order, enriched companies only
    company_ids = [uuid.UUID(enriched["companies"][str(cid)]) for cid in crust_ids
                   if str(cid) in enriched["companies"]]

    concepts = [str(c.value) for c in spec.companies if c.op == "semantic"]
    if concepts:
        def run_concepts() -> dict[str, Any]:
            out = gate(db, clients, company_ids, concepts, budget)
            db.commit()
            return out

        gated = runner.step("concepts", run_concepts)
        company_ids = [uuid.UUID(i) for i in gated["kept"]]

    def run_grants() -> dict[str, Any]:
        if spec.grants is None:
            return {"skipped": "no grant filter", "verified": [], "unverifiable": []}
        since = months_before(as_of, spec.window_months or DEFAULT_GRANT_MONTHS)
        companies = [(cid, db.get_one(Company, cid).name) for cid in company_ids]
        out = check_grants(db, clients, companies, since, budget)
        db.commit()
        return out

    runner.step("grants", run_grants)

    def run_candidates() -> dict[str, Any]:
        ids = [str(get_or_create_candidate(db, search_id, cid).id) for cid in company_ids]
        db.commit()
        return {"candidate_ids": ids, "count": len(ids)}

    runner.step("candidates", run_candidates)

    def run_score() -> dict[str, Any]:
        # scoring reads only stored facts: no paid calls, so no budget check here
        scored = score_search(db, search_id)
        search = db.get(Search, search_id)
        if search is not None:
            search.status = SearchStatus.done
        db.commit()
        return {"scored": len(scored)}

    runner.step("score", run_score)
