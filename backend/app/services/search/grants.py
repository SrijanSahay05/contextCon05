"""Web-verified grants: search grant portals and news, fetch pages, keep only quoted claims.

A grant becomes a fact only when the LLM's quote is found verbatim on the fetched page;
otherwise the company is reported `unverifiable` with what was searched — never guessed.
"""

import html
import re
import uuid
from datetime import date, datetime, time, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.integrations.llm import quote_check
from app.models.enums import ExtractedBy, SubjectType
from app.models.evidence import Fact
from app.services.clients import Clients
from app.services.evidence.facts_mapper import parse_date
from app.services.search.discovery import Budget

GRANT = "grant"
GRANT_SITES = ["startupindia.gov.in", "seedfund.startupindia.gov.in", "birac.nic.in",
               "dst.gov.in"]
MAX_PAGES = 3
MAX_PAGE_CHARS = 30_000
# each company costs ≤ 2 searches + 3 fetches = 5 credits; this caps grants at 75 a run
MAX_GRANT_COMPANIES = 15

SYSTEM = (
    "You read one web page and list government or institutional grants awarded to the "
    "named company. Only include a grant if the page states it was awarded to that "
    "company. `quote` must be copied exactly from the page text. Return an empty list "
    "when there is none."
)


class GrantClaim(BaseModel):
    program: str
    amount: str | None = None
    date: str | None = None
    quote: str


class GrantClaims(BaseModel):
    grants: list[GrantClaim] = Field(default_factory=list)


def page_text(content: str) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", content)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def _queries(name: str) -> list[dict[str, Any]]:
    sites = " OR ".join(f"site:{s}" for s in GRANT_SITES)
    return [
        {"query": f'"{name}" grant ({sites})', "sources": ["web"]},
        {"query": f'"{name}" grant awarded', "sources": ["news"]},
    ]


def check_company(
    db: Session, clients: Clients, company_id: uuid.UUID, name: str, since: date | None,
    budget: Budget,
) -> dict[str, Any]:
    """Search, fetch and extract grants for one company. Flushes; the caller commits."""
    start = int(datetime.combine(since, time(), timezone.utc).timestamp()) if since else None
    queries = _queries(name)
    urls: list[str] = []
    for q in queries:
        budget()
        found = clients.web.search(q["query"], sources=q["sources"], start_date=start)
        for r in (found.data or {}).get("results") or []:
            if isinstance(r.get("url"), str) and r["url"] not in urls:
                urls.append(r["url"])

    fact_ids: list[int] = []
    for url in urls[:MAX_PAGES]:
        budget()
        fetched = clients.web.fetch(url)
        page = (fetched.data or [{}])[0]
        if not page.get("success") or not page.get("content"):
            continue
        text = page_text(page["content"])
        claims = clients.llm.extract(
            GrantClaims, SYSTEM,
            f"Company: {name}\nURL: {url}\n\nPage text:\n{text[:MAX_PAGE_CHARS]}",
        )
        for claim in claims.grants:
            if not quote_check(text, claim.quote):
                continue  # the model's quote isn't on the page: drop it, never guess
            value = {k: v for k, v in claim.model_dump().items() if v}
            locator = {"url": url, "quote": claim.quote}
            as_of = parse_date(claim.date)
            db.execute(insert(Fact).values(
                subject_type=SubjectType.company, subject_id=company_id, predicate=GRANT,
                value=value, as_of=as_of, source_id=fetched.source_id, locator=locator,
                extracted_by=ExtractedBy.llm,
            ).on_conflict_do_nothing())
            fact_id = db.scalar(select(Fact.id).where(
                Fact.subject_id == company_id, Fact.predicate == GRANT,
                Fact.source_id == fetched.source_id, Fact.value == value,
            ))
            if fact_id is not None:
                fact_ids.append(fact_id)
    db.flush()
    return {"company_id": str(company_id), "fact_ids": fact_ids,
            "searched": [q["query"] for q in queries], "urls": urls[:MAX_PAGES]}


def check_grants(
    db: Session, clients: Clients, companies: list[tuple[uuid.UUID, str]], since: date | None,
    budget: Budget,
) -> dict[str, Any]:
    verified: list[dict[str, Any]] = []
    unverifiable: list[dict[str, Any]] = []
    for company_id, name in companies[:MAX_GRANT_COMPANIES]:
        result = check_company(db, clients, company_id, name, since, budget)
        (verified if result["fact_ids"] else unverifiable).append(result)
    unverifiable += [{"company_id": str(cid), "fact_ids": [], "searched": [],
                      "reason": "grant credit cap reached"}
                     for cid, _ in companies[MAX_GRANT_COMPANIES:]]
    return {"verified": verified, "unverifiable": unverifiable}
