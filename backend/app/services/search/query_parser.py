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
# Spellings seen in live autocomplete (2026-11-22). Each is resolved with the exact/contains
# rule and the matches are combined, so "BITS, Pilani" and "Birla Institute of Technology &
# Science" both count while "Birla Institute of Technology, Mesra" (a different school) doesn't.
_BITS = [
    "Birla Institute of Technology and Science",
    "Birla Institute of Technology & Science",
    "BITS Pilani",
    "BITS, Pilani",
    "BITS-Pilani",
]
SCHOOL_ALIASES: dict[str, list[str]] = {
    "bitsian": _BITS,
    "bitsians": _BITS,
    "bits": _BITS,
    "bits pilani": _BITS,
    "iitian": ["Indian Institute of Technology"],
    "iitians": ["Indian Institute of Technology"],
    "iit": ["Indian Institute of Technology"],
    "iim": ["Indian Institute of Management"],
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
    ranking_description: str | None = Field(
        default=None,
        description="One or two plain sentences describing the companies this query is "
                    "after: what they build, for whom, and where. Used only to rank "
                    "results, never to exclude them. The thesis may add detail here.",
    )


SYSTEM = """You split a venture investor's search query into structured terms.
Rules for every field except `ranking_description`:
- Only use words that are in the query. Never add schools, industries, countries,
  programmes or numbers that the query does not state, even if the thesis suggests them.
- Every `phrase` must be copied verbatim from the query.
- Keep ambiguous or informal terms as written (e.g. 'BITSian'); do not expand or guess.
- Leave a list empty when the query says nothing about it.
The fund's thesis is context only; it never adds terms.
`ranking_description` is different: write it in your own words from the query, adding
detail from the thesis where the query is vague (e.g. which customers or sub-sector). It
only orders results, so it must describe what the companies do, not invent constraints."""

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


def _lookups(term: Term, key: str) -> tuple[list[str], bool]:
    """Texts to look up, and whether they are alias spellings."""
    if key == "schools":
        alias = SCHOOL_ALIASES.get(term.phrase.strip().casefold())
        if alias:
            return alias, True
    return [term.lookup or term.phrase], False


def _resolve(
    autocomplete: Callable[[dict[str, Any]], CrustResult], field: str, text: str,
    prefer_exact: bool = True,
) -> tuple[list[str], list[str]]:
    """(exact matches, else values containing `text`; all suggestions). Weaker suggestions
    are only offered to the partner, never taken. Alias spellings skip the exact-first
    rule so campus variants ("BITS Pilani, Hyderabad Campus") are kept."""
    body = {"field": field, "query": text, "limit": AUTOCOMPLETE_LIMIT}
    data = autocomplete(body).data or {}
    suggestions = [s["value"] for s in data.get("suggestions") or [] if s.get("value")]
    needle = text.casefold()
    exact = [s for s in suggestions if s.casefold() == needle] if prefer_exact else []
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
            matches, suggestions = [], []
            texts, is_alias = _lookups(term, key)
            for text in texts:
                found, offered = _resolve(calls[route], field, text, prefer_exact=not is_alias)
                matches += [m for m in found if m not in matches]
                suggestions += [o for o in offered if o not in suggestions]
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
    if parsed.ranking_description and parsed.ranking_description.strip():
        spec.ranking_query = parsed.ranking_description.strip()
    if parsed.grants:
        grants = parsed.grants
        spec.grants = grants.model_copy(
            update={"programs": [p for p in grants.programs if said(p)]}
        )
    return spec, unresolved
