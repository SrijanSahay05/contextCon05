"""`memo` job: gather evidence → write with the LLM → post-check → store a new version.

Payload: `{candidate_id, investor_id}`.
"""

import json
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.actions import Memo
from app.models.dd import Document
from app.models.enums import SubjectType
from app.models.evidence import Fact
from app.models.search import Candidate, Search, Signal
from app.repositories import scores
from app.repositories.sources import get_source
from app.schemas.memo import MemoCitation
from app.services.actions import memo
from app.services.clients import clients_for_run
from app.services.evidence.sources import citation, fact_out
from app.services.jobs.registry import register
from app.services.jobs.steps import StepRunner, ensure_budget

SECTIONS = ["Summary", "Thesis fit", "Team", "Traction", "Market and competition",
            "Funding history", "Strong signals", "Risks and red flags", "Open questions",
            "Recommendation"]

SYSTEM = (
    "You write a venture investment memo using ONLY the numbered evidence list provided. "
    "Use exactly these markdown sections, in order, each as a `## ` heading: "
    + "; ".join(SECTIONS) + ". "
    "Every factual sentence ends, before its full stop, with citations copied from the "
    "evidence list, like `[f:123]` or `[c:<id>]`. Never state a number or date that is not "
    "in a cited item; never cite an id that is not in the list. Where the evidence is "
    "missing, write that you can't verify it instead of guessing. Founder claims ([c:...]) "
    "are what the founder says, not established facts: say so, and mention their "
    "verification result when one is given."
)


def _evidence(db: Session, candidate: Candidate) -> list[dict[str, Any]]:
    people = [p.id for p, _ in scores.founders(db, candidate.company_id)]
    facts = db.scalars(select(Fact).where(
        ((Fact.subject_type == SubjectType.company) & (Fact.subject_id == candidate.company_id))
        | ((Fact.subject_type == SubjectType.person) & Fact.subject_id.in_(people))
    ).order_by(Fact.id)).all()
    items = []
    for fact in facts:
        out = fact_out(db, fact).model_dump(mode="json")
        items.append({"key": f"f:{fact.id}", "fact_id": fact.id, "claim_id": None, **out})
    for claim, ver in scores.claims_with_verification(db, candidate.id):
        doc = db.get(Document, claim.document_id) if claim.document_id else None
        source = get_source(db, doc.source_id) if doc and doc.source_id else None
        if source is None:  # shortcut: claims with no stored source can't be cited yet
            continue
        cite = citation(source).model_copy(update={
            "locator": {"page": claim.page, "quote": claim.quote}, "quote": claim.quote})
        items.append({
            "key": f"c:{claim.id}", "fact_id": None, "claim_id": str(claim.id),
            "predicate": claim.predicate, "value": claim.value,
            "as_of": claim.as_of.isoformat() if claim.as_of else None,
            "verification": ver.result.value if ver else "unverified",
            "citation": cite.model_dump(mode="json"),
        })
    return items


def _context(db: Session, candidate: Candidate) -> dict[str, Any]:
    search = db.get(Search, candidate.search_id)
    thesis = scores.thesis_for(db, search) if search else None
    signals = db.scalars(select(Signal).where(Signal.candidate_id == candidate.id)
                         .order_by(Signal.created_at, Signal.id)).all()
    return {
        "score": float(candidate.score) if candidate.score is not None else None,
        "suggested_action": candidate.suggested_action,
        "breakdown": [{k: c.get(k) for k in ("key", "score", "reason", "fact_ids", "claim_ids")}
                      for c in candidate.breakdown],
        "signals": [{"kind": s.kind.value, "text": s.text, "fact_ids": s.fact_ids,
                     "claim_ids": s.claim_ids} for s in signals],
        "thesis_points": thesis.points if thesis else [],
    }


@register(memo.JOB_KIND)
def memo_run(db: Session, runner: StepRunner, payload: dict[str, Any]) -> None:
    candidate_id = uuid.UUID(payload["candidate_id"])
    candidate = scores.get_owned(db, candidate_id, uuid.UUID(payload["investor_id"]))

    def gather() -> dict[str, Any]:
        return {"items": _evidence(db, candidate), "context": _context(db, candidate)}

    gathered = runner.step("gather", gather)
    items: list[dict[str, Any]] = gathered["items"]

    def write() -> str:
        ensure_budget(db, runner.run_id)
        lines = [memo.evidence_line(n, item) for n, item in enumerate(items, 1)]
        prompt = (
            "Evidence (the only things you may cite):\n" + ("\n".join(lines) or "(none)")
            + "\n\nScoring context (not citable; cite the evidence ids it points to):\n"
            + json.dumps(gathered["context"], default=str)
        )
        return clients_for_run(runner.run_id).llm.write(SYSTEM, prompt)

    draft = runner.step("write", write)

    def check() -> dict[str, Any]:
        kept, removed = memo.post_check(draft, {i["key"]: i for i in items})
        return {"markdown": kept, "removed": removed}

    checked = runner.step("check", check)

    def store() -> dict[str, Any]:
        markdown, used = memo.render_refs(checked["markdown"])
        by_key = {i["key"]: i for i in items}
        citations = [
            MemoCitation.model_validate({**by_key[key], "ref": n}).model_dump(mode="json")
            for n, key in enumerate(used, 1)
        ]
        db.execute(update(Memo).where(Memo.candidate_id == candidate_id).values(stale=True))
        version = (db.scalar(select(func.max(Memo.version))
                             .where(Memo.candidate_id == candidate_id)) or 0) + 1
        row = Memo(candidate_id=candidate_id, version=version, markdown=markdown,
                   citations=citations, removed=checked["removed"], stale=False)
        db.add(row)
        db.commit()
        return {"memo_id": str(row.id), "version": version}

    runner.step("store", store)
