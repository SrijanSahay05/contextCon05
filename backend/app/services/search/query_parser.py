"""Plain-language query → `FilterSpec`.

The LLM only splits the query into phrases; every categorical value in the result is an
exact Crustdata autocomplete value (free endpoints), never an LLM value. Phrases the LLM
returns that are not in the query are dropped.
"""

import calendar
import json
from collections.abc import Callable
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from app.integrations.crustdata import CrustResult
from app.integrations.llm import quote_check
from app.schemas.search import Condition, FilterSpec, GrantFilter, Unresolved
from app.services.clients import Clients

AUTOCOMPLETE_LIMIT = 10

# Informal school names → the indexed name to autocomplete with (data, not logic).
SCHOOL_ALIASES = {
    "bitsian": "Birla Institute of Technology and Science",
    "bitsians": "Birla Institute of Technology and Science",
    "bits": "Birla Institute of Technology and Science",
    "iitian": "Indian Institute of Technology",
    "iitians": "Indian Institute of Technology",
    "iit": "Indian Institute of Technology",
    "iim": "Indian Institute of Management",
}


class Term(BaseModel):
    phrase: str = Field(description="The words exactly as they appear in the query.")
    lookup: str | None = Field(
        default=None,
        description="Optional standard spelling to look up (e.g. 'Financial Services' for "
                    "'fintech'). Leave empty when unsure.",
    )


class Window(BaseModel):
    phrase: str = Field(description="The time words exactly as in the query.")
    months: int = Field(ge=1)


class FoundedAfter(BaseModel):
    phrase: str
    year: int


class ParsedQuery(BaseModel):
    schools: list[Term] = Field(default_factory=list, description="Founders' schools.")
    founder_titles: list[Term] = Field(
        default_factory=list, description="Founder/role titles, e.g. 'founder', 'CTO'."
    )
    founder_countries: list[Term] = Field(
        default_factory=list, description="Where the founders are based (country)."
    )
    industries: list[Term] = Field(
        default_factory=list, description="Named industries, e.g. 'fintech', 'healthcare'."
    )
    concepts: list[Term] = Field(
        default_factory=list,
        description="What the company builds when it isn't a plain industry, e.g. 'deeptech'.",
    )
    hq_countries: list[Term] = Field(default_factory=list, description="Company HQ country.")
    founded_after: FoundedAfter | None = None
    funding_window: Window | None = Field(
        default=None, description="Raised/funded/granted within this many months."
    )
    grants: GrantFilter | None = Field(
        default=None, description="Set when the query asks for government or other grants."
    )


SYSTEM = """You split a venture investor's search query into structured terms.
Rules:
- Only use words that are in the query. Never add schools, industries, countries,
  programmes or numbers that the query does not state, even if the thesis suggests them.
- Every `phrase` must be copied verbatim from the query.
- Keep ambiguous or informal terms as written (e.g. 'BITSian'); do not expand or guess.
- Leave a list empty when the query says nothing about it.
The fund's thesis is context only; it never adds terms."""

# (route, crustdata field, op label) per categorical ParsedQuery list
PERSON = "person"
COMPANY = "company"
FIELDS: dict[str, tuple[str, str, str]] = {
    "schools": (PERSON, "education.schools.school", "Founder studied at"),
    "founder_titles": (PERSON, "experience.employment_details.current.title", "Founder is"),
    "founder_countries": (PERSON, "basic_profile.location.country", "Founder based in"),
    "industries": (COMPANY, "basic_info.industries", "Industry"),
    "hq_countries": (COMPANY, "locations.country", "HQ in"),
}


def months_before(day: date, months: int) -> date:
    y, m = divmod(day.year * 12 + day.month - 1 - months, 12)
    return date(y, m + 1, min(day.day, calendar.monthrange(y, m + 1)[1]))


def _lookup(term: Term, key: str) -> str:
    if key == "schools":
        alias = SCHOOL_ALIASES.get(term.phrase.strip().casefold())
        if alias:
            return alias
    return term.lookup or term.phrase


def _resolve(
    autocomplete: Callable[[dict[str, Any]], CrustResult], field: str, text: str
) -> tuple[list[str], list[str]]:
    """(exact matches, else values containing `text`; all suggestions). Weaker suggestions
    are only offered to the partner, never taken."""
    body = {"field": field, "query": text, "limit": AUTOCOMPLETE_LIMIT}
    data = autocomplete(body).data or {}
    suggestions = [s["value"] for s in data.get("suggestions") or [] if s.get("value")]
    needle = text.casefold()
    exact = [s for s in suggestions if s.casefold() == needle]
    return exact or [s for s in suggestions if needle in s.casefold()], suggestions


def parse_query(
    clients: Clients, query_text: str, thesis_points: list[Any] | None,
    as_of: date | None = None,
) -> tuple[FilterSpec, list[Unresolved]]:
    context = json.dumps(thesis_points or [], default=str)[:4000]
    parsed = clients.llm.extract(
        ParsedQuery, SYSTEM, f"Query: {query_text}\n\nThesis (context only): {context}"
    )

    def said(phrase: str) -> bool:
        return quote_check(query_text, phrase)

    spec, unresolved = FilterSpec(), []
    calls = {PERSON: clients.crustdata.person_autocomplete,
             COMPANY: clients.crustdata.company_autocomplete}
    for key, (route, field, label) in FIELDS.items():
        for term in getattr(parsed, key):
            if not said(term.phrase):
                continue
            matches, suggestions = _resolve(calls[route], field, _lookup(term, key))
            if not matches:
                unresolved.append(Unresolved(term=term.phrase, suggestions=suggestions))
                continue
            group = spec.people if route == PERSON else spec.companies
            group.append(Condition(field=field, op="in", value=matches,
                                   display=f"{label} {term.phrase}"))

    for term in parsed.concepts:
        if said(term.phrase):
            spec.companies.append(Condition(field="search.query", op="semantic",
                                            value=term.phrase, display=term.phrase))
    if parsed.founded_after and said(parsed.founded_after.phrase):
        year = parsed.founded_after.year
        spec.companies.append(Condition(field="basic_info.year_founded", op=">", value=year,
                                        display=f"Founded after {year}"))
    window = parsed.funding_window
    if window and said(window.phrase):
        spec.window_months = window.months
        since = months_before(as_of or date.today(), window.months)
        spec.funding.append(Condition(field="funding.last_fundraise_date", op=">",
                                      value=since.isoformat(), display=window.phrase))
    if parsed.grants:
        grants = parsed.grants
        spec.grants = grants.model_copy(
            update={"programs": [p for p in grants.programs if said(p)]}
        )
    return spec, unresolved
