"""`verify_claims` job: check a document's claims, tick the checklist, re-score.

Payload: `{candidate_id, document_id}` (enqueued by document ingestion). Each claim is
verified once, so re-running the job adds nothing. Contradictions reach the score as
contradicted claims (`scores.claim_items`), which the engine penalises and flags.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dd import Document, Verification
from app.models.enums import DDItemKind as K
from app.models.enums import DDItemStatus, DDStage, SnapshotTrigger
from app.models.enums import VerificationResult as R
from app.models.search import Candidate
from app.repositories import dd as repo
from app.repositories import scores
from app.services.dd.verify import Tolerance, verify
from app.services.jobs.registry import register
from app.services.jobs.steps import StepRunner
from app.services.scoring.rules import Item
from app.services.scoring.service import score_candidate

# which claims answer which checklist item, besides a document of the item's own kind
ITEM_PREDICATES: dict[K, frozenset[str]] = {
    K.financials: frozenset({"revenue_usd", "arr_usd", "burn_usd"}),
    K.cap_table: frozenset({"funding_total_usd", "funding_round", "last_round_type"}),
    K.grant_letter: frozenset({"grant"}),
    K.customer_refs: frozenset({"customers"}),
    K.answer: frozenset({"founder", "employment", "education"}),
}


def item_status(results: list[R]) -> DDItemStatus:
    """The worst news wins: one contradiction marks the item contradicted."""
    for result, status in ((R.contradicted, DDItemStatus.contradicted),
                           (R.verified, DDItemStatus.verified),
                           (R.unverifiable, DDItemStatus.unverifiable)):
        if result in results:
            return status
    return DDItemStatus.received


@register("verify_claims")
def verify_claims(db: Session, runner: StepRunner, payload: dict[str, Any]) -> None:
    candidate_id = uuid.UUID(payload["candidate_id"])
    document_id = uuid.UUID(payload["document_id"])

    def check() -> dict[str, Any]:
        candidate = db.get(Candidate, candidate_id)
        assert candidate is not None
        candidate.dd_stage = DDStage.verifying
        people = [p.id for p, _ in scores.founders(db, candidate.company_id)]
        facts = scores.fact_items(db, candidate.company_id, people)
        claims = repo.document_claims(db, document_id)
        done = set(db.scalars(select(Verification.claim_id).where(
            Verification.claim_id.in_([c.id for c in claims]))))
        tolerance = Tolerance()
        added = 0
        for claim in claims:
            if claim.id in done:
                continue
            item = Item(str(claim.id), claim.predicate, claim.value, claim.as_of)
            result, fact_ids, note = verify(item, facts, tolerance)
            db.add(Verification(claim_id=claim.id, result=result, fact_ids=fact_ids, note=note,
                                tolerance_used=tolerance.as_json()))
            added += 1
        db.commit()
        return {"claims": len(claims), "verified_now": added}

    runner.step("verify", check)

    def tick_items() -> dict[str, Any]:
        document = db.get(Document, document_id)
        request = repo.latest_request(db, candidate_id)
        if document is None or request is None:
            return {"items": 0}
        latest = scores.claims_with_verification(db, candidate_id)
        mine = [(c, v) for c, v in latest if c.document_id == document_id]
        updated = 0
        for item in repo.items(db, request.id):
            relevant = mine if item.kind == document.kind else [
                (c, v) for c, v in mine if c.predicate in ITEM_PREDICATES.get(item.kind, ())]
            if item.kind != document.kind and not relevant:
                continue
            item.status = item_status([v.result for _, v in relevant if v is not None])
            item.document_id = item.document_id or document_id
            updated += 1
        db.commit()
        return {"items": updated}

    runner.step("items", tick_items)

    def rescore() -> dict[str, Any]:
        candidate = score_candidate(db, candidate_id, SnapshotTrigger.dd_ingest)
        db.commit()
        return {"score": float(candidate.score) if candidate.score is not None else None}

    runner.step("rescore", rescore)

    def stage() -> dict[str, Any]:
        candidate = db.get(Candidate, candidate_id)
        assert candidate is not None
        candidate.dd_stage = DDStage.ready_for_decision
        db.commit()
        return {"stage": DDStage.ready_for_decision.value}

    runner.step("stage", stage)
