"""Fixed mappings from one Crustdata enrich record to sourced fact drafts (no LLM).

Every draft carries the JSON path of the field it came from, so a fact's `locator`
(`{"path": ...}`) points back into the raw payload stored for its source. Pass
`prefix` (e.g. `"[0].matches[0].company_data"`) when the record sits inside a larger
response, so the path resolves against the whole stored payload. Missing or empty
fields produce no fact; unparseable dates keep the fact with `as_of=None`.

Predicate vocabulary (scoring, thesis and verification depend on these exact names):

Company (subject_type=company)
- `name` str ← basic_info.name
- `domain` str ← basic_info.primary_domain
- `description` str ← basic_info.description
- `industries` list[str] ← taxonomy.professional_network_industries (else taxonomy.categories)
- `hq_country` str ← locations.country
- `hq_city` str ← locations.headquarters (as given, may include state/country)
- `year_founded` int ← basic_info.year_founded
- `headcount_total` int ← headcount.total; as_of = updated_at, else latest timeseries date
- `headcount_at` int, one per headcount.timeseries[i]; as_of = that point's date
- `headcount_by_function` dict[str, int] ← headcount.by_role_absolute; as_of as headcount_total
- `funding_total_usd` number ← funding.total_investment_usd
- `last_round_type` str ← funding.last_round_type
- `last_round_date` str (ISO date) ← funding.last_fundraise_date; as_of = that date
- `funding_round` {round_type, amount_usd, investors, lead_investors}, one per
  funding.milestones[i]; investor strings split into lists; as_of = funding_date
- `investors` list[str] ← funding.investors
- `founder` {name, crustdata_person_id, title}, one per people.founders[i]
- `news_item` {title, url}, one per news[i]; as_of = article_publish_date
- `web_traffic_monthly` {domain, monthly_visitors}, one per web_traffic.domain_traffic entry
- `competitors` list[str] ← competitors.all_domains

Person (subject_type=person)
- `name` str ← basic_profile.name
- `headline` str ← basic_profile.headline
- `current_title` str ← basic_profile.current_title
- `current_employer` {name, crustdata_company_id} ← experience.employment_details.current[0]
- `employment` {title, company_name, crustdata_company_id, start, end}, one per job in
  employment_details.current[] then past[]; dates as ISO strings; as_of = start
- `education` {school, degree, field, start, end}, one per education.schools[i]
- `location` str ← basic_profile.location.raw
- `skills` list[str] ← skills.professional_network_skills

Composite values drop null members; a composite with no members produces no fact.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ExtractedBy, SubjectType
from app.models.evidence import Fact

# company predicates
NAME = "name"
DOMAIN = "domain"
DESCRIPTION = "description"
INDUSTRIES = "industries"
HQ_COUNTRY = "hq_country"
HQ_CITY = "hq_city"
YEAR_FOUNDED = "year_founded"
HEADCOUNT_TOTAL = "headcount_total"
HEADCOUNT_AT = "headcount_at"
HEADCOUNT_BY_FUNCTION = "headcount_by_function"
FUNDING_TOTAL_USD = "funding_total_usd"
LAST_ROUND_TYPE = "last_round_type"
LAST_ROUND_DATE = "last_round_date"
FUNDING_ROUND = "funding_round"
INVESTORS = "investors"
FOUNDER = "founder"
NEWS_ITEM = "news_item"
WEB_TRAFFIC_MONTHLY = "web_traffic_monthly"
COMPETITORS = "competitors"
# person predicates (NAME shared)
HEADLINE = "headline"
CURRENT_TITLE = "current_title"
CURRENT_EMPLOYER = "current_employer"
EMPLOYMENT = "employment"
EDUCATION = "education"
LOCATION = "location"
SKILLS = "skills"


@dataclass(frozen=True)
class FactDraft:
    predicate: str
    value: Any
    as_of: date | None
    path: str


def parse_date(value: Any) -> date | None:
    """`2019-01-01`, `2019-01-01T00:00:00+00:00` → date; anything else → None."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _iso(value: Any) -> Any:
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else value


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in value.items() if v is not None and v != "" and v != []}


def _split(names: Any) -> Any:
    if isinstance(names, str):
        return [n.strip() for n in names.split(",") if n.strip()] or None
    return names


class _Drafts:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.items: list[FactDraft] = []

    def add(self, predicate: str, value: Any, path: str, as_of: date | None = None) -> None:
        if isinstance(value, dict):
            value = _compact(value)
        if value is None or value == "" or value == [] or value == {}:
            return
        full = f"{self.prefix}.{path}" if self.prefix else path
        self.items.append(FactDraft(predicate, value, as_of, full))


def _section(record: dict[str, Any], key: str) -> dict[str, Any]:
    value = record.get(key)
    return value if isinstance(value, dict) else {}


def _list(container: dict[str, Any], key: str) -> list[Any]:
    value = container.get(key)
    return value if isinstance(value, list) else []


def map_company(company_data: dict[str, Any], prefix: str = "") -> list[FactDraft]:
    out = _Drafts(prefix)
    basic = _section(company_data, "basic_info")
    out.add(NAME, basic.get("name"), "basic_info.name")
    out.add(DOMAIN, basic.get("primary_domain"), "basic_info.primary_domain")
    out.add(DESCRIPTION, basic.get("description"), "basic_info.description")
    out.add(YEAR_FOUNDED, basic.get("year_founded"), "basic_info.year_founded")

    taxonomy = _section(company_data, "taxonomy")
    if taxonomy.get("professional_network_industries"):
        out.add(INDUSTRIES, taxonomy["professional_network_industries"],
                "taxonomy.professional_network_industries")
    else:
        out.add(INDUSTRIES, taxonomy.get("categories"), "taxonomy.categories")

    locations = _section(company_data, "locations")
    out.add(HQ_COUNTRY, locations.get("country"), "locations.country")
    out.add(HQ_CITY, locations.get("headquarters"), "locations.headquarters")

    headcount = _section(company_data, "headcount")
    series = _list(headcount, "timeseries")
    dated = [parse_date(p.get("date")) for p in series if isinstance(p, dict)]
    data_date = parse_date(company_data.get("updated_at")) or max(
        (d for d in dated if d), default=None
    )
    out.add(HEADCOUNT_TOTAL, headcount.get("total"), "headcount.total", data_date)
    for i, point in enumerate(series):
        if isinstance(point, dict):
            out.add(HEADCOUNT_AT, point.get("employee_count"),
                    f"headcount.timeseries[{i}].employee_count", parse_date(point.get("date")))
    out.add(HEADCOUNT_BY_FUNCTION, headcount.get("by_role_absolute"),
            "headcount.by_role_absolute", data_date)

    funding = _section(company_data, "funding")
    out.add(FUNDING_TOTAL_USD, funding.get("total_investment_usd"), "funding.total_investment_usd")
    out.add(LAST_ROUND_TYPE, funding.get("last_round_type"), "funding.last_round_type")
    last_date = funding.get("last_fundraise_date")
    out.add(LAST_ROUND_DATE, _iso(last_date), "funding.last_fundraise_date", parse_date(last_date))
    for i, m in enumerate(_list(funding, "milestones")):
        if isinstance(m, dict):
            out.add(FUNDING_ROUND, {
                "round_type": m.get("round_type"),
                "amount_usd": m.get("amount_usd"),
                "investors": _split(m.get("investors")),
                "lead_investors": _split(m.get("lead_investors")),
            }, f"funding.milestones[{i}]", parse_date(m.get("funding_date") or m.get("date")))
    out.add(INVESTORS, funding.get("investors"), "funding.investors")

    for i, f in enumerate(_list(_section(company_data, "people"), "founders")):
        if isinstance(f, dict):
            profile = _section(f, "basic_profile")
            out.add(FOUNDER, {
                "name": profile.get("name"),
                "crustdata_person_id": f.get("crustdata_person_id"),
                "title": profile.get("current_title"),
            }, f"people.founders[{i}]")

    for i, n in enumerate(_list(company_data, "news")):
        if isinstance(n, dict):
            out.add(NEWS_ITEM, {"title": n.get("article_title"), "url": n.get("article_url")},
                    f"news[{i}]", parse_date(n.get("article_publish_date")))

    traffic = _section(_section(company_data, "web_traffic"), "domain_traffic")
    for domain, metrics in traffic.items():
        if isinstance(metrics, dict) and metrics.get("monthly_visitors") is not None:
            out.add(WEB_TRAFFIC_MONTHLY,
                    {"domain": metrics.get("domain") or domain,
                     "monthly_visitors": metrics["monthly_visitors"]},
                    f'web_traffic.domain_traffic["{domain}"].monthly_visitors')

    out.add(COMPETITORS, _section(company_data, "competitors").get("all_domains"),
            "competitors.all_domains")
    return out.items


def map_person(person_data: dict[str, Any], prefix: str = "") -> list[FactDraft]:
    out = _Drafts(prefix)
    profile = _section(person_data, "basic_profile")
    out.add(NAME, profile.get("name"), "basic_profile.name")
    out.add(HEADLINE, profile.get("headline"), "basic_profile.headline")
    out.add(CURRENT_TITLE, profile.get("current_title"), "basic_profile.current_title")
    out.add(LOCATION, _section(profile, "location").get("raw"), "basic_profile.location.raw")

    jobs = _section(_section(person_data, "experience"), "employment_details")
    current = _list(jobs, "current")
    if current and isinstance(current[0], dict):
        out.add(CURRENT_EMPLOYER, {"name": current[0].get("name"),
                                   "crustdata_company_id": current[0].get("crustdata_company_id")},
                "experience.employment_details.current[0]")
    for bucket in ("current", "past"):
        for i, job in enumerate(_list(jobs, bucket)):
            if isinstance(job, dict):
                out.add(EMPLOYMENT, {
                    "title": job.get("title"),
                    "company_name": job.get("name"),
                    "crustdata_company_id": job.get("crustdata_company_id"),
                    "start": _iso(job.get("start_date")),
                    "end": _iso(job.get("end_date")),
                }, f"experience.employment_details.{bucket}[{i}]",
                    parse_date(job.get("start_date")))

    for i, s in enumerate(_list(_section(person_data, "education"), "schools")):
        if isinstance(s, dict):
            out.add(EDUCATION, {
                "school": s.get("school"),
                "degree": s.get("degree"),
                "field": s.get("field_of_study"),
                "start": _iso(s.get("start_date")),
                "end": _iso(s.get("end_date")),
            }, f"education.schools[{i}]")

    out.add(SKILLS, _section(person_data, "skills").get("professional_network_skills"),
            "skills.professional_network_skills")
    return out.items


def _key(predicate: str, value: Any, as_of: date | None) -> tuple[str, str, date | None]:
    return predicate, json.dumps(value, sort_keys=True), as_of


def persist_facts(
    db: Session,
    subject_type: SubjectType,
    subject_id: uuid.UUID,
    drafts: list[FactDraft],
    source_id: uuid.UUID,
) -> list[Fact]:
    """Insert drafts as `rule` facts; a fact already stored for the same subject and
    source with the same (predicate, value, as_of) is returned instead of duplicated.
    Flushes, never commits."""
    existing = db.scalars(
        select(Fact).where(
            Fact.subject_type == subject_type,
            Fact.subject_id == subject_id,
            Fact.source_id == source_id,
        )
    ).all()
    seen = {_key(f.predicate, f.value, f.as_of): f for f in existing}
    result: list[Fact] = []
    for d in drafts:
        key = _key(d.predicate, d.value, d.as_of)
        if key not in seen:
            seen[key] = Fact(
                subject_type=subject_type, subject_id=subject_id, predicate=d.predicate,
                value=d.value, as_of=d.as_of, source_id=source_id,
                locator={"path": d.path}, extracted_by=ExtractedBy.rule,
            )
            db.add(seen[key])
        result.append(seen[key])
    db.flush()
    return result
