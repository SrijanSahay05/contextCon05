"""Uploaded documents: validation and storage on disk, and text per page into Mongo."""

import hashlib
import uuid
from pathlib import Path

from fastapi import UploadFile
from pypdf import PdfReader
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.mongo import mongo_db
from app.errors import ApiError, ErrorCode
from app.models.dd import Document
from app.models.enums import CandidateStatus, DDItemKind, DDStage, DocumentOrigin, RunKind
from app.models.search import Candidate
from app.repositories import documents as repo
from app.schemas.document import DocumentOut
from app.services.jobs import queue

PDF = "application/pdf"
CSV = "text/csv"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXTENSIONS = {PDF: "pdf", CSV: "csv", XLSX: "xlsx"}
JOB_KIND = "ingest_document"
PAGES = "document_pages"
CHUNK = 1 << 20


def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
    data = bytearray()
    while chunk := file.file.read(CHUNK):
        data += chunk
        if len(data) > max_bytes:
            raise ApiError(413, ErrorCode.validation_error,
                           f"File is larger than {max_bytes // CHUNK} MB",
                           {"max_mb": max_bytes // CHUNK})
    return bytes(data)


def upload(db: Session, candidate: Candidate, file: UploadFile, kind: DDItemKind) -> DocumentOut:
    """Store the file once per candidate and queue its ingestion; a repeat returns the first."""
    settings = get_settings()
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in EXTENSIONS:
        raise ApiError(422, ErrorCode.validation_error, "Only PDF, XLSX or CSV files are accepted",
                       {"mime": mime, "allowed": sorted(EXTENSIONS)})
    data = _read_capped(file, settings.upload_max_mb * CHUNK)
    if mime == PDF and not data.startswith(b"%PDF"):
        raise ApiError(422, ErrorCode.validation_error, "File is not a PDF", {"mime": mime})
    sha256 = hashlib.sha256(data).hexdigest()

    existing = repo.by_sha(db, candidate.id, sha256)
    if existing is not None:
        return repo.to_out(db, existing)

    path = Path(settings.upload_dir) / str(candidate.id) / f"{sha256}.{EXTENSIONS[mime]}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    doc = Document(candidate_id=candidate.id, kind=kind, origin=DocumentOrigin.vc_upload,
                   storage_path=str(path), mime=mime, sha256=sha256)
    db.add(doc)
    try:
        db.flush()
    except IntegrityError:  # the same file uploaded concurrently: the other request won
        db.rollback()
        return repo.to_out(db, repo.by_sha(db, candidate.id, sha256))
    payload = {"document_id": str(doc.id), "candidate_id": str(candidate.id)}
    run = queue.create_run(db, RunKind.dd, {**payload, "filename": file.filename})
    queue.enqueue(db, JOB_KIND, payload, f"ingest:{doc.id}", run.id)
    if candidate.status == CandidateStatus.in_dd:
        candidate.dd_stage = DDStage.ingesting
    db.commit()
    return repo.to_out(db, doc)


def parse_pdf(path: str) -> list[str]:
    """Text per page; a page without text is kept as "" so page numbers stay right."""
    return [page.extract_text() or "" for page in PdfReader(path).pages]


def parse_csv(path: str) -> list[str]:
    return [Path(path).read_text(encoding="utf-8", errors="replace")]


def store_pages(document_id: uuid.UUID, pages: list[str]) -> None:
    for number, text in enumerate(pages, start=1):
        mongo_db[PAGES].update_one({"document_id": str(document_id), "page": number},
                                   {"$set": {"text": text}}, upsert=True)


def load_pages(document_id: uuid.UUID) -> list[str]:
    rows = mongo_db[PAGES].find({"document_id": str(document_id)}).sort("page", 1)
    return [str(r["text"]) for r in rows]
