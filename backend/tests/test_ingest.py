from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.mongo import mongo_db
from app.integrations.llm import FakeLLM
from app.models.dd import Claim, Document
from app.models.entities import Company
from app.models.enums import CandidateStatus, DDStage, ParseStatus, RunKind
from app.models.identity import Investor
from app.models.runs import Job
from app.models.search import Candidate, Search
from app.services import clients
from app.services.dd import ingest, ingest_job
from app.services.jobs import queue
from app.services.jobs.registry import HANDLERS
from app.services.jobs.steps import StepRunner

# Team-made test pages for a fictional company; not any real company's deck.
DECK = [
    "Ledgerline - team-made TEST deck, not a real company\nA team of 40 engineers in Pune",
    "Traction\nWe raised $4.5M in our seed round in 2026.",
]


def make_pdf(pages: list[str]) -> bytes:
    """A minimal text PDF, one page per string (Helvetica, one line per text line)."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        lines = " T* ".join(f"({line})Tj" for line in text.splitlines())
        stream = f"BT /F1 12 Tf 14 TL 50 750 Td {lines} ET"
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {len(objects)} 0 R >>")
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return out


PDF = make_pdf(DECK)
CLAIMS = {"claims": [
    {"predicate": "headcount_total", "value": "40 engineers", "page": 1,
     "quote": "A team of 40 engineers in Pune"},
    {"predicate": "funding_total_usd", "value": "$4.5M", "page": 2,
     "quote": "We raised $4.5M in our seed round"},
    {"predicate": "headcount_total", "value": 60, "page": 2, "quote": "a team of 60"},
]}


@pytest.fixture(autouse=True)
def uploads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    yield tmp_path


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr(ingest_job, "clients_for_run", lambda run_id: clients.clients_for_run(
        run_id, transport=httpx.MockTransport(lambda r: httpx.Response(500)),
        llm_transport=fake))
    return fake


def seed(db: Session, status: CandidateStatus = CandidateStatus.in_dd) -> tuple[str, Candidate]:
    investor = Investor(name="Partner")
    company = Company(crustdata_company_id=101, name="Ledgerline", domain="ledgerline.test")
    db.add_all([investor, company])
    db.flush()
    search = Search(investor_id=investor.id, query_text="fintech", parsed_filters={},
                    unresolved=[])
    db.add(search)
    db.flush()
    candidate = Candidate(search_id=search.id, company_id=company.id, breakdown=[],
                          status=status)
    db.add(candidate)
    db.commit()
    return str(investor.id), candidate


def post(client: TestClient, investor_id: str, candidate: Candidate, data: bytes = PDF,
         mime: str = "application/pdf", name: str = "deck.pdf") -> Any:
    return client.post(f"/candidates/{candidate.id}/documents",
                       headers={"X-Investor-Id": investor_id},
                       files={"file": (name, data, mime)}, data={"kind": "deck"})


def jobs(db: Session, kind: str) -> list[Job]:
    return list(db.scalars(select(Job).where(Job.kind == kind)))


def test_upload_stores_file_and_queues_once(client: TestClient, db: Session,
                                            uploads: Path) -> None:
    investor_id, candidate = seed(db)
    first = post(client, investor_id, candidate)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["origin"] == "vc_upload" and body["parse_status"] == "pending"
    assert body["filename"] == "deck.pdf" and body["run_id"]
    assert (uploads / str(candidate.id) / f"{body['sha256']}.pdf").read_bytes() == PDF
    db.refresh(candidate)
    assert candidate.dd_stage == DDStage.ingesting

    again = post(client, investor_id, candidate, name="deck-copy.pdf")
    assert again.status_code == 201 and again.json() == body
    assert len(jobs(db, "ingest_document")) == 1
    assert db.scalar(select(func.count()).select_from(Document)) == 1


def test_upload_rejects_type_size_and_other_investors(
        client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    investor_id, candidate = seed(db)
    bad = post(client, investor_id, candidate, b"MZ...", "application/x-msdownload", "a.exe")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
    fake_pdf = post(client, investor_id, candidate, b"not a pdf")
    assert fake_pdf.status_code == 422

    monkeypatch.setattr(get_settings(), "upload_max_mb", 1)
    big = post(client, investor_id, candidate, b"%PDF" + b"0" * (1 << 20))
    assert big.status_code == 413 and big.json()["error"]["code"] == "validation_error"

    other = Investor(name="Someone else")
    db.add(other)
    db.commit()
    assert post(client, str(other.id), candidate).status_code == 404
    assert jobs(db, "ingest_document") == []


def test_parse_pdf_pages(tmp_path: Path) -> None:
    path = tmp_path / "deck.pdf"
    path.write_bytes(make_pdf([DECK[0], "", DECK[1]]))
    pages = ingest.parse_pdf(str(path))
    assert len(pages) == 3 and pages[1] == ""
    assert "40 engineers" in pages[0] and "$4.5M" in pages[2]


def run_job(db: Session, doc_id: str, candidate: Candidate) -> None:
    run = queue.create_run(db, RunKind.dd, {})
    db.commit()
    HANDLERS["ingest_document"](db, StepRunner(db, run.id), {
        "document_id": doc_id, "candidate_id": str(candidate.id)})


def test_job_stores_quoted_claims_and_queues_verify_once(
        client: TestClient, db: Session, llm: FakeLLM) -> None:
    investor_id, candidate = seed(db)
    doc_id = post(client, investor_id, candidate).json()["id"]
    llm.queue(CLAIMS, CLAIMS)
    run_job(db, doc_id, candidate)
    run_job(db, doc_id, candidate)  # a second run adds nothing

    claims = {c.predicate: c for c in db.scalars(select(Claim))}
    assert len(db.scalars(select(Claim)).all()) == 2  # the "team of 60" quote is not on page 2
    assert (claims["headcount_total"].value, claims["headcount_total"].page) == (40, 1)
    assert claims["funding_total_usd"].value == 4500000
    assert claims["funding_total_usd"].quote == "We raised $4.5M in our seed round"
    doc = db.get_one(Document, doc_id)
    db.refresh(doc)
    db.refresh(candidate)
    assert (doc.parse_status, doc.page_count) == (ParseStatus.parsed, 2)
    assert candidate.dd_stage == DDStage.verifying
    [verify] = jobs(db, "verify_claims")
    assert verify.payload == {"candidate_id": str(candidate.id), "document_id": doc_id}
    pages = list(mongo_db["document_pages"].find({"document_id": doc_id}))
    assert sorted(p["page"] for p in pages) == [1, 2]


def test_csv_is_one_page_and_xlsx_is_not_supported(
        client: TestClient, db: Session, llm: FakeLLM) -> None:
    investor_id, candidate = seed(db, CandidateStatus.shortlist)
    csv_id = post(client, investor_id, candidate, b"metric,value\nARR,$300k\n", "text/csv",
                  "kpis.csv").json()["id"]
    llm.queue({"claims": [{"predicate": "arr_usd", "value": "$300k", "page": 1,
                           "quote": "ARR,$300k"}]})
    run_job(db, csv_id, candidate)
    [claim] = db.scalars(select(Claim)).all()
    assert claim.value == 300000
    db.refresh(candidate)
    assert candidate.dd_stage is None  # not in DD: stage untouched

    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    xlsx_id = post(client, investor_id, candidate, b"PK\x03\x04", xlsx, "f.xlsx").json()["id"]
    run_job(db, xlsx_id, candidate)
    doc: Any = db.get(Document, xlsx_id)
    db.refresh(doc)
    assert doc.parse_status == ParseStatus.failed
    assert len(jobs(db, "verify_claims")) == 1
