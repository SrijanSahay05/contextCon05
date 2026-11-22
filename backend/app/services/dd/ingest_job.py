"""`ingest_document` job: parse → claims → hand over to `verify_claims`.

Payload: `{document_id, candidate_id}`. Every step is resumable and idempotent.
"""

import uuid
from typing import Any

from pypdf.errors import PdfReadError
from sqlalchemy.orm import Session

from app.models.dd import Document
from app.models.enums import CandidateStatus, DDStage, ParseStatus
from app.models.search import Candidate
from app.repositories import documents as repo
from app.services.clients import clients_for_run
from app.services.dd import ingest
from app.services.dd.claims import extract_claims
from app.services.jobs import queue
from app.services.jobs.registry import register
from app.services.jobs.steps import StepRunner, ensure_budget

VERIFY_JOB = "verify_claims"


@register(ingest.JOB_KIND)
def ingest_document(db: Session, runner: StepRunner, payload: dict[str, Any]) -> None:
    doc = db.get(Document, uuid.UUID(payload["document_id"]))
    if doc is None:
        raise ValueError(f"document {payload['document_id']} not found")

    def parse() -> dict[str, Any]:
        reason = None
        try:
            if doc.mime == ingest.PDF:
                pages = ingest.parse_pdf(doc.storage_path)
            elif doc.mime == ingest.CSV:
                pages = ingest.parse_csv(doc.storage_path)
            else:
                reason = "not supported yet"
        except (PdfReadError, OSError) as exc:
            reason = f"could not read the file: {exc}"
        if reason is not None:
            doc.parse_status = ParseStatus.failed
            db.commit()
            return {"failed": reason}
        ingest.store_pages(doc.id, pages)
        doc.page_count = len(pages)
        db.commit()
        return {"page_count": len(pages)}

    if "failed" in runner.step("parse", parse):
        return

    def claims() -> dict[str, Any]:
        ensure_budget(db, runner.run_id)
        drafts = extract_claims(clients_for_run(runner.run_id), ingest.load_pages(doc.id))
        added = repo.add_claims(db, doc, drafts)
        db.commit()
        return {"extracted": len(drafts), "added": added}

    runner.step("claims", claims)

    def hand_over() -> dict[str, Any]:
        doc.parse_status = ParseStatus.parsed
        candidate = db.get_one(Candidate, doc.candidate_id)
        if candidate.status == CandidateStatus.in_dd:
            candidate.dd_stage = DDStage.verifying
        verify = {"candidate_id": str(doc.candidate_id), "document_id": str(doc.id)}
        job = queue.enqueue(db, VERIFY_JOB, verify, f"verify:{doc.id}", runner.run_id)
        db.commit()
        return {"verify_job_id": job.id}

    runner.step("next", hand_over)
