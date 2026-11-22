"""Fit rerank: how well does each candidate match what the search is after?

Runs on the descriptions the company search already returned, *before* enrichment, so a
company that doesn't fit costs a search row (0.03 credits) rather than an enrich (2).

Each company gets a 0-3 fit from its own description, with an exact quote as proof:

- Concepts the query states (e.g. "deeptech") are hard: a company scoring below
  `search_concept_min_fit` is excluded, with the reason.
- The ranking description (query + thesis) is soft: it only reorders, never excludes, so
  nothing the investor didn't type can remove a company.

A fit claimed without a quote found in the description counts as 0. No description means
no verdict: excluded under a hard concept, left in place (after rated fits) otherwise.
"""

import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.llm import quote_check
from app.models.enums import ExtractedBy, SubjectType
from app.models.evidence import Fact
from app.services.clients import Clients

CONCEPT_MATCH = "concept_match"
BATCH = 20
UNRATED_FIT = 1  # rank position for companies without a verdict under a soft criterion

SYSTEM = """You rate how well each company fits what a venture investor is looking for,
using only the company text given. Never use outside knowledge.
Fit scale:
3 = the company's core product is what is described
2 = closely adjacent (same customers or same technology, different angle)
1 = mentioned only in passing, or a loose connection
0 = no fit, or the company is an investor, agency, consultancy or services firm
For fit 1-3, `quote` must be words copied exactly from that company's text that show it.
For fit 0, leave `quote` empty. Rate every company, by its `index`."""


class Fit(BaseModel):
    index: int
    fit: int = Field(ge=0, le=3)
    quote: str = Field(default="", description="Exact words from the company text, or ''.")
    reason: str = Field(description="One short sentence.")


class FitBatch(BaseModel):
    ratings: list[Fit]


def criteria(concepts: list[str], ranking_query: str | None) -> str:
    parts = ([f"Must be: {', '.join(concepts)}."] if concepts else [])
    parts += [f"Looking for: {ranking_query}"] if ranking_query else []
    return "\n".join(parts)


def _rate(clients: Clients, wanted: str, batch: list[dict[str, Any]]) -> dict[int, Fit]:
    listing = "\n\n".join(
        f"[{i}] {c.get('name') or 'Unnamed'}\n{c['description']}" for i, c in enumerate(batch))
    out = clients.llm.extract(FitBatch, SYSTEM, f"{wanted}\n\nCompanies:\n{listing}",
                              model=get_settings().llm_fast_model)
    rated: dict[int, Fit] = {}
    for r in out.ratings:
        if 0 <= r.index < len(batch) and r.index not in rated:
            # a fit must be shown by the company's own words, so the citation is exact
            if r.fit and not quote_check(batch[r.index]["description"], r.quote):
                r = r.model_copy(update={
                    "fit": 0, "quote": "",
                    "reason": "claimed fit not supported by the description's own words"})
            rated[r.index] = r
    return rated


def rerank(
    clients: Clients,
    candidates: list[dict[str, Any]],
    concepts: list[str],
    ranking_query: str | None,
    budget: Callable[[], None],
) -> dict[str, Any]:
    """Candidates (discovery output) → kept in fit order, excluded with reasons, and every
    rating, as a JSON-able step output."""
    wanted = criteria(concepts, ranking_query)
    hard = bool(concepts)
    min_fit = get_settings().search_concept_min_fit
    described = [c for c in candidates if c.get("description")]

    fits: dict[int, Fit] = {}
    for start in range(0, len(described), BATCH):
        batch = described[start:start + BATCH]
        budget()
        for i, rated in _rate(clients, wanted, batch).items():
            fits[int(batch[i]["crustdata_company_id"])] = rated

    kept: list[tuple[int, int, dict[str, Any]]] = []  # (fit, retrieval rank, candidate)
    excluded: list[dict[str, Any]] = []
    for rank, c in enumerate(candidates):
        cid = int(c["crustdata_company_id"])
        verdict = fits.get(cid)
        row = {**c, "fit": verdict.fit if verdict else None,
               "quote": verdict.quote if verdict else "",
               "reason": verdict.reason if verdict else None}
        if hard and verdict is None:
            reason = ("no company description to check the concept against"
                      if not c.get("description") else "the model returned no rating")
            excluded.append({"crustdata_company_id": cid, "name": c.get("name"),
                             "reason": reason})
        elif hard and verdict is not None and verdict.fit < min_fit:
            excluded.append({"crustdata_company_id": cid, "name": c.get("name"),
                             "fit": verdict.fit, "reason": verdict.reason})
        else:
            kept.append((verdict.fit if verdict else UNRATED_FIT, rank, row))
    kept.sort(key=lambda t: (-t[0], t[1]))  # best fit first; ties keep the search order
    return {"criteria": wanted, "hard": hard, "kept": [row for _, _, row in kept],
            "excluded": excluded}


def record_fits(db: Session, kept: list[dict[str, Any]], companies: dict[str, str]) -> int:
    """Store a `concept_match` fact for each enriched company with a quoted fit, citing the
    search response the description came from. Idempotent per company and source."""
    stored = 0
    for c in kept:
        company_id = companies.get(str(c["crustdata_company_id"]))
        if not (company_id and c.get("fit") and c.get("quote") and c.get("source_id")):
            continue
        subject, source = uuid.UUID(company_id), uuid.UUID(c["source_id"])
        exists = db.scalar(select(Fact.id).where(
            Fact.subject_type == SubjectType.company, Fact.subject_id == subject,
            Fact.source_id == source, Fact.predicate == CONCEPT_MATCH))
        if exists:
            continue
        db.add(Fact(
            subject_type=SubjectType.company, subject_id=subject, predicate=CONCEPT_MATCH,
            value={"fit": c["fit"], "quote": c["quote"], "reason": c["reason"]},
            as_of=None, source_id=source, locator={"path": c["path"], "quote": c["quote"]},
            extracted_by=ExtractedBy.llm,
        ))
        stored += 1
    db.flush()
    return stored
