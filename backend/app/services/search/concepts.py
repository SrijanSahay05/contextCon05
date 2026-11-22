"""Concept gate: does each company really fit the query's concepts (e.g. "deeptech")?

Semantic search *ranks*, it doesn't filter: live, the top results for "deeptech" among
BITS founders' companies included a fintech and a cosmetics brand. Each company is kept
only if its own description, quoted exactly, shows the concept; the quote is stored as
a fact citing the description's source. No description means no verdict, so the company
is excluded with that reason rather than guessed.
"""

import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.llm import quote_check
from app.models.entities import Company
from app.models.enums import ExtractedBy, SubjectType
from app.models.evidence import Fact
from app.repositories.facts import facts_for
from app.services.clients import Clients
from app.services.evidence import facts_mapper as fm

CONCEPT_MATCH = "concept_match"

SYSTEM = (
    "You judge whether a company fits an investor's concept using only the company text "
    "given. Answer from the text alone, never from outside knowledge. If it fits, `quote` "
    "must be words copied exactly from the text that show it. If the text doesn't show it, "
    "set `matches` to false and leave `quote` empty."
)


class ConceptVerdict(BaseModel):
    matches: bool
    quote: str = Field(default="", description="Exact words from the company text, or ''.")
    reason: str = Field(description="One sentence on why it does or doesn't fit.")


def gate(
    db: Session,
    clients: Clients,
    company_ids: list[uuid.UUID],
    concepts: list[str],
    budget: Callable[[], None],
) -> dict[str, Any]:
    """Returns kept company ids (in order) and the excluded ones with reasons."""
    kept: list[str] = []
    excluded: list[dict[str, Any]] = []
    concept = ", ".join(concepts)
    for company_id in company_ids:
        company = db.get_one(Company, company_id)
        descriptions = facts_for(db, SubjectType.company, company_id, fm.DESCRIPTION)
        if not descriptions:
            excluded.append({"company_id": str(company_id), "name": company.name,
                             "reason": "no company description to check the concept against"})
            continue
        description = descriptions[-1]
        industries = facts_for(db, SubjectType.company, company_id, fm.INDUSTRIES)
        text = str(description.value)
        context = f"{text}\nIndustries: {', '.join(industries[-1].value)}" if industries else text

        budget()
        verdict = clients.llm.extract(
            ConceptVerdict, SYSTEM,
            f"Concept: {concept}\n\nCompany: {company.name}\n\nCompany text:\n{context}",
            model=get_settings().llm_fast_model,
        )
        # the quote must come from the description itself, so the citation is exact
        if verdict.matches and quote_check(text, verdict.quote):
            db.add(Fact(
                subject_type=SubjectType.company, subject_id=company_id,
                predicate=CONCEPT_MATCH,
                value={"concept": concept, "quote": verdict.quote, "reason": verdict.reason},
                as_of=description.as_of, source_id=description.source_id,
                locator={**description.locator, "quote": verdict.quote},
                extracted_by=ExtractedBy.llm,
            ))
            kept.append(str(company_id))
        else:
            reason = verdict.reason if not verdict.matches else (
                "claimed match not supported by the description's own words")
            excluded.append({"company_id": str(company_id), "name": company.name,
                             "reason": reason})
    db.flush()
    return {"concept": concept, "kept": kept, "excluded": excluded}
