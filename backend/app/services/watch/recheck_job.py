"""`recheck` job: snapshot_before → enrich → diff → rescore → event.

Payload: `{candidate_id, investor_id, source?}`; `source` is the webhook delivery's
source id when Crustdata triggered the re-check. Every step is resumable.
"""

import uuid
from collections.abc import Iterable
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.actions import WatchEvent
from app.models.entities import Company
from app.models.enums import RunKind, SnapshotTrigger, SubjectType
from app.models.evidence import Fact
from app.models.runs import Job
from app.models.search import Candidate
from app.repositories import watch as repo
from app.repositories.candidates import company_facts
from app.schemas.common import RunAccepted
from app.services.clients import clients_for_run
from app.services.evidence.entities import upsert_company
from app.services.evidence.facts_mapper import map_company, persist_facts
from app.services.jobs import queue
from app.services.jobs.registry import register
from app.services.jobs.steps import StepRunner, ensure_budget
from app.services.onboarding.firm import accepted
from app.services.scoring.service import score_candidate
from app.services.search.discovery import ENRICH_FIELDS
from app.services.watch.diff import Snapshot, diff, suggest

JOB_KIND = "recheck"


def snapshot(facts: Iterable[Fact]) -> Snapshot:
    """Predicate → values from the newest source that reported that predicate."""
    latest: dict[str, uuid.UUID] = {}
    ordered = sorted(facts, key=lambda f: f.id)
    for f in ordered:
        latest[f.predicate] = f.source_id
    out: Snapshot = {}
    for f in ordered:
        if latest[f.predicate] == f.source_id:
            out.setdefault(f.predicate, []).append(f.value)
    return out


def start_recheck(
    db: Session, candidate: Candidate, investor_id: uuid.UUID, idempotency_key: str,
    source_id: uuid.UUID | None = None,
) -> RunAccepted:
    """Create a `recheck` run and job once per key; a repeat returns the same run. Commits."""
    job = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if job is not None and job.run_id is not None:
        return accepted(job.run_id)
    payload = {"candidate_id": str(candidate.id), "investor_id": str(investor_id)}
    if source_id is not None:
        payload["source"] = str(source_id)
    run = queue.create_run(db, RunKind.recheck, payload)
    queue.enqueue(db, JOB_KIND, payload, idempotency_key, run.id)
    db.commit()
    return accepted(run.id)


def daily_key(candidate_id: uuid.UUID) -> str:
    return f"{JOB_KIND}:{candidate_id}:{date.today().isoformat()}"


@register(JOB_KIND)
def recheck(db: Session, runner: StepRunner, payload: dict[str, Any]) -> None:
    candidate_id = uuid.UUID(payload["candidate_id"])
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise ValueError(f"candidate {candidate_id} not found")
    company = db.get_one(Company, candidate.company_id)
    crust_id = company.crustdata_company_id

    before = runner.step("snapshot_before", lambda: snapshot(company_facts(db, company.id)))

    def run_enrich() -> dict[str, Any]:
        ensure_budget(db, runner.run_id)
        result = clients_for_run(runner.run_id).crustdata.company_enrich(
            {"crustdata_company_ids": [crust_id], "fields": ENRICH_FIELDS})
        facts: list[Fact] = []
        for i, entry in enumerate(result.data or []):
            for m in entry.get("matches") or []:
                data = m.get("company_data")
                if isinstance(data, dict) and data.get("crustdata_company_id") == crust_id:
                    upsert_company(db, data)
                    facts += persist_facts(db, SubjectType.company, company.id,
                                           map_company(data, f"[{i}].matches[0].company_data"),
                                           result.source_id)
                    break
        db.commit()
        return {"source_id": str(result.source_id), "after": snapshot(facts)}

    enriched = runner.step("enrich", run_enrich)
    changes = runner.step("diff", lambda: diff(before, enriched["after"]))

    def run_rescore() -> dict[str, Any]:
        scored = score_candidate(db, candidate_id, SnapshotTrigger.watch_event)
        db.commit()
        return {"score": float(scored.score) if scored.score is not None else None}

    rescored = runner.step("rescore", run_rescore)

    def run_event() -> dict[str, Any]:
        watch = repo.watch_for_candidate(db, candidate_id)
        if not changes or watch is None:
            return {"event_id": None, "changes": len(changes), "watched": watch is not None}
        event = WatchEvent(
            watch_id=watch.id, changes=changes,
            source_id=uuid.UUID(payload.get("source") or enriched["source_id"]),
            suggested_action=suggest(changes, rescored["score"]),
        )
        db.add(event)
        db.commit()
        return {"event_id": str(event.id), "changes": len(changes), "watched": True}

    runner.step("event", run_event)
