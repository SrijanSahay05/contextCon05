"""Documents and the claims extracted from them."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dd import Claim, Document
from app.models.runs import Job, Run
from app.schemas.document import DocumentOut


def by_sha(db: Session, candidate_id: uuid.UUID, sha256: str) -> Document | None:
    return db.scalar(select(Document).where(Document.candidate_id == candidate_id,
                                            Document.sha256 == sha256))


def to_out(db: Session, doc: Document | None) -> DocumentOut:
    assert doc is not None
    run_id = db.scalar(select(Job.run_id).where(Job.idempotency_key == f"ingest:{doc.id}"))
    run = db.get(Run, run_id) if run_id else None
    # shortcut: `document` has no filename column, so it lives on the ingest run's subject
    filename = run.subject.get("filename") if run else None
    return DocumentOut(id=doc.id, candidate_id=doc.candidate_id, kind=doc.kind, origin=doc.origin,
                       filename=filename, mime=doc.mime, sha256=doc.sha256,
                       parse_status=doc.parse_status, page_count=doc.page_count, run_id=run_id)


def add_claims(db: Session, doc: Document, drafts: list[Any]) -> int:
    """Insert claims once per (document, page, quote); returns how many were new."""
    seen = {(c.page, c.quote) for c in db.scalars(select(Claim).where(
        Claim.document_id == doc.id))}
    added = 0
    for d in drafts:
        if (d.page, d.quote) in seen:
            continue
        seen.add((d.page, d.quote))
        db.add(Claim(candidate_id=doc.candidate_id, document_id=doc.id, page=d.page,
                     quote=d.quote, predicate=d.predicate, value=d.value, as_of=d.as_of))
        added += 1
    return added
