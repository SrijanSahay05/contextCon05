"""Turn a `FilterSpec` into Crustdata searches, then enrich the candidates into facts.

Discovery runs a people route (founders matching the people filters → their current
employers) and a company route (company filters, semantic query, funding), and merges
them by Crustdata company id. Enrichment stores company, founder and open-role facts
through the 1A mappers so every fact's locator resolves against its stored payload.
"""

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Company
from app.models.enums import SubjectType
from app.schemas.search import Condition, FilterSpec
from app.services.clients import Clients
from app.services.evidence.entities import link_person, upsert_company, upsert_person
from app.services.evidence.facts_mapper import (
    FactDraft,
    map_company,
    map_person,
    parse_date,
    persist_facts,
)

WITHIN_LIMIT = 500  # employer ids passed to the company search
SEARCH_LIMIT = 100
# the pool handed to the fit rerank; only the top `search_enrich_cap` are enriched
MAX_CANDIDATES = SEARCH_LIMIT
FOUNDED_FIELD = "basic_info.year_founded"
ENRICH_BATCH = 25
JOB_LIMIT = 20
OPEN_ROLES = "open_roles"
ENRICH_FIELDS = ["basic_info", "headcount", "funding", "taxonomy", "locations"]
PERSON_FIELDS = ["basic_profile", "experience"]
SEARCH_PERSON_FIELDS = ["crustdata_person_id", "basic_profile", "experience", "social_handles"]
FOUNDER_TITLES = ["founder", "co-founder", "cofounder"]
TITLE_FIELD = "experience.employment_details.current.title"

# Short names the query parser may emit → Crustdata filter paths; dotted names not listed
# here are passed through as Crustdata paths unchanged.
PEOPLE_FIELDS = {
    "school": "education.schools.school",
    "education.school": "education.schools.school",
    "degree": "education.schools.degree",
    "field_of_study": "education.schools.field_of_study",
    "title": TITLE_FIELD,
    "current_title": TITLE_FIELD,
    "past_company": "experience.employment_details.past.name",
    "location": "basic_profile.location.full_location",
}
COMPANY_FIELDS = {
    "industries": "basic_info.industries",
    "industry": "basic_info.industries",
    "hq_country": "locations.country",
    "country": "locations.country",
    "hq_city": "locations.headquarters",
    "year_founded": "basic_info.year_founded",
    "headcount": "headcount.total",
    "headcount_total": "headcount.total",
    "employee_count_range": "basic_info.employee_count_range",
    "last_funding_round_type": "funding.last_round_type",
    "last_round_type": "funding.last_round_type",
    "funding_total_usd": "funding.total_investment_usd",
    "last_round_amount_usd": "funding.last_round_amount_usd",
    "last_fundraise_date": "funding.last_fundraise_date",
    "investors": "funding.investors",
}
OPS = {"=": "=", "in": "in", ">": ">", "<": "<", "contains": "(.)", "semantic": "(.)"}

Budget = Callable[[], None]


def _condition(c: Condition, aliases: dict[str, str]) -> dict[str, Any]:
    field = aliases.get(c.field, c.field)
    op = OPS[c.op]
    if op == "(.)" and isinstance(c.value, list):  # fuzzy match takes one string
        return {"op": "or", "conditions": [
            {"field": field, "type": op, "value": str(v)} for v in c.value]}
    return {"field": field, "type": op, "value": c.value}


def _and(conditions: list[dict[str, Any]]) -> dict[str, Any]:
    return conditions[0] if len(conditions) == 1 else {"op": "and", "conditions": conditions}


def _founder_titles() -> dict[str, Any]:
    return {"op": "or", "conditions": [
        {"field": TITLE_FIELD, "type": "[.]", "value": t} for t in FOUNDER_TITLES]}


def months_before(day: date, months: int) -> date:
    total = day.year * 12 + day.month - 1 - months
    return date(total // 12, total % 12 + 1, min(day.day, 28))


def people_request(spec: FilterSpec) -> dict[str, Any]:
    conditions = [_condition(c, PEOPLE_FIELDS) for c in spec.people]
    return {
        "filters": _and(conditions + [_founder_titles()]),
        "fields": SEARCH_PERSON_FIELDS,
        "limit": SEARCH_LIMIT,
    }


def ranking_text(spec: FilterSpec) -> str:
    """What the search ranks by: the plan's description plus the query's own concept words
    (kept verbatim so the keyword half of hybrid search can match them)."""
    concepts = [str(c.value) for c in spec.companies if c.op == "semantic"]
    parts = [spec.ranking_query] if spec.ranking_query else []
    parts += [c for c in concepts if c.casefold() not in (spec.ranking_query or "").casefold()]
    return ". ".join(p.strip().rstrip(".") for p in parts if p.strip())


def startup_gates(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Always-on filters that keep out long-established companies. Only basic_info fields,
    which carry no premium filter charge. A founded year in the query wins."""
    year = get_settings().search_founded_from_year
    if year <= 0 or FOUNDED_FIELD in json.dumps(conditions):
        return []
    return [{"field": FOUNDED_FIELD, "type": "=>", "value": year}]


def company_request(
    spec: FilterSpec, as_of: date, within: list[int] | None = None
) -> dict[str, Any]:
    """`within` restricts the company search to these ids (the people route's employers)."""
    conditions = [_condition(c, COMPANY_FIELDS)
                  for c in spec.companies + spec.funding if c.op != "semantic"]
    if spec.window_months and spec.funding:
        conditions.append({"field": "funding.last_fundraise_date", "type": "=>",
                           "value": months_before(as_of, spec.window_months).isoformat()})
    conditions += startup_gates(conditions)
    if within is not None:
        conditions.append({"field": "crustdata_company_id", "type": "in", "value": within})
    # basic_info carries the description the fit rerank reads, at the base result price
    body: dict[str, Any] = {"fields": ["basic_info"], "limit": SEARCH_LIMIT}
    if conditions:
        body["filters"] = _and(conditions)
    if query := ranking_text(spec):
        body["search"] = {"query": query, "mode": get_settings().search_mode}
    return body


def _current_employers(profile: dict[str, Any]) -> list[int]:
    jobs = ((profile.get("experience") or {}).get("employment_details") or {}).get("current")
    # 0 / missing ids show up live for founders without a resolved employer
    return [int(j["crustdata_company_id"]) for j in jobs or []
            if isinstance(j, dict) and (j.get("crustdata_company_id") or 0) > 0]


def _described(company: dict[str, Any], i: int, source_id: str) -> dict[str, Any]:
    """Name and description from a search row, with where they sit in the raw response."""
    info = company.get("basic_info") or {}
    out: dict[str, Any] = {"name": info.get("name")}
    if isinstance(info.get("description"), str) and info["description"].strip():
        out.update(description=info["description"], source_id=source_id,
                   path=f"companies[{i}].basic_info.description")
    return out


def discover(clients: Clients, spec: FilterSpec, as_of: date, budget: Budget) -> dict[str, Any]:
    """Candidates in rank order with `found_by`, plus name and description when the
    company search returned them (the fit rerank reads these before anything is enriched).

    With people and company terms, the company search (incl. the semantic ranking) runs
    *within* the people route's employers, so every candidate satisfies both. Live, the
    two routes run separately had no overlap, and a union fallback returned companies
    that matched only half the request.
    """
    route_counts: dict[str, int] = {}
    details: dict[int, dict[str, Any]] = {}
    people_ids: list[int] | None = None
    if spec.people:
        budget()
        found = clients.crustdata.person_search(people_request(spec))
        people_ids = list(dict.fromkeys(
            cid for p in (found.data or {}).get("profiles") or [] for cid in _current_employers(p)
        ))
        route_counts["people"] = len(people_ids)

    # a ranking description alone still runs the company search: it orders the people
    # route's employers and applies the startup gates
    has_company_terms = bool(spec.companies or spec.funding or spec.ranking_query)
    if people_ids is not None and not has_company_terms:
        mode, ranked = "people", people_ids
    elif people_ids is not None and not people_ids:
        mode, ranked = "people_then_company", []
    elif has_company_terms:
        budget()
        within = people_ids[:WITHIN_LIMIT] if people_ids is not None else None
        found = clients.crustdata.company_search(company_request(spec, as_of, within))
        ranked = []
        for i, c in enumerate((found.data or {}).get("companies") or []):
            cid = int(c.get("crustdata_company_id") or 0)
            if cid > 0:
                ranked.append(cid)
                details.setdefault(cid, _described(c, i, str(found.source_id)))
        route_counts["company"] = len(set(ranked))
        mode = "company" if people_ids is None else "people_then_company"
    else:
        mode, ranked = "none", []

    found_by = ["people", "company"] if mode == "people_then_company" else [mode]
    return {
        "mode": mode,
        "route_counts": route_counts,
        "candidates": [{"crustdata_company_id": cid, "found_by": found_by, **details.get(cid, {})}
                       for cid in list(dict.fromkeys(ranked))[:MAX_CANDIDATES]],
    }


def _match(entry: dict[str, Any], key: str) -> dict[str, Any] | None:
    matches = entry.get("matches") or []
    data = matches[0].get(key) if matches else None
    return data if isinstance(data, dict) else None


def _profile_url(profile: dict[str, Any]) -> str | None:
    handles = profile.get("social_handles") or {}
    url = (handles.get("professional_network_identifier") or {}).get("profile_url")
    return url if isinstance(url, str) else None


def open_role_drafts(data: Any) -> list[FactDraft]:
    drafts = []
    for i, job in enumerate((data or {}).get("job_listings") or []):
        details = job.get("job_details") or {}
        posted = (job.get("metadata") or {}).get("date_added")
        day = parse_date(posted)
        value = {k: v for k, v in {
            "title": details.get("title"), "function": details.get("category"),
            "posted_at": day.isoformat() if day else posted}.items() if v}
        if value.get("title"):
            drafts.append(FactDraft(OPEN_ROLES, value, day, f"job_listings[{i}]"))
    return drafts


def enrich(
    db: Session, clients: Clients, crust_ids: list[int], budget: Budget
) -> dict[str, Any]:
    """Companies → facts; founders (current founder-titled people) → person facts and
    `founder` links; open jobs → `open_roles` facts. Flushes; the caller commits."""
    crust = clients.crustdata
    rows: dict[int, Company] = {}
    company_facts = 0
    for start in range(0, len(crust_ids), ENRICH_BATCH):
        budget()
        result = crust.company_enrich({
            "crustdata_company_ids": crust_ids[start:start + ENRICH_BATCH],
            "fields": ENRICH_FIELDS,
        })
        for i, entry in enumerate(result.data or []):
            data = _match(entry, "company_data")
            if data is None or data.get("crustdata_company_id") is None:
                continue
            company = upsert_company(db, data)
            rows[int(data["crustdata_company_id"])] = company
            company_facts += len(persist_facts(
                db, SubjectType.company, company.id,
                map_company(data, f"[{i}].matches[0].company_data"), result.source_id))

    companies = {cid: row.id for cid, row in rows.items()}
    # founders of every candidate: people whose current job there has a founder title
    founders: dict[str, set[int]] = {}  # profile URL → candidate employers
    if companies:
        budget()
        found = crust.person_search({
            "filters": {"op": "and", "conditions": [
                {"field": "experience.employment_details.current.company_id", "type": "in",
                 "value": list(companies)},
                _founder_titles(),
            ]},
            "fields": SEARCH_PERSON_FIELDS,
            "limit": SEARCH_LIMIT,
        })
        for profile in (found.data or {}).get("profiles") or []:
            url = _profile_url(profile)
            employers = set(_current_employers(profile)) & set(companies)
            if url and employers:
                founders.setdefault(url, set()).update(employers)

    urls = list(founders)
    person_facts = linked = 0
    for start in range(0, len(urls), ENRICH_BATCH):
        budget()
        result = crust.person_enrich({"professional_network_profile_urls":
                                      urls[start:start + ENRICH_BATCH],
                                      "fields": PERSON_FIELDS})
        for i, entry in enumerate(result.data or []):
            data = _match(entry, "person_data")
            if data is None or data.get("crustdata_person_id") is None:
                continue
            person = upsert_person(db, data)
            person_facts += len(persist_facts(
                db, SubjectType.person, person.id,
                map_person(data, f"[{i}].matches[0].person_data"), result.source_id))
            batch = urls[start:start + ENRICH_BATCH]
            url = entry.get("matched_on") or (batch[i] if i < len(batch) else None)
            for cid in founders.get(str(url), set()):
                link_person(db, rows[cid], person, role="founder")
                linked += 1

    roles = 0
    for cid, company_id in companies.items():
        budget()
        result = crust.job_search({
            "filters": {"field": "company.basic_info.company_id", "type": "=", "value": cid},
            "fields": ["job_details.title", "job_details.category", "job_details.url",
                       "metadata.date_added"],
            "sorts": [{"field": "metadata.date_added", "order": "desc"}],
            "limit": JOB_LIMIT,
        })
        roles += len(persist_facts(db, SubjectType.company, company_id,
                                   open_role_drafts(result.data), result.source_id))

    return {
        "companies": {str(cid): str(company_id) for cid, company_id in companies.items()},
        "missing": [cid for cid in crust_ids if cid not in companies],
        "company_facts": company_facts,
        "founders_found": len(urls),
        "founder_links": linked,
        "person_facts": person_facts,
        "open_roles": roles,
    }
