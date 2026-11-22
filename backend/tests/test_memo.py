import uuid
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.llm import FakeLLM
from app.models.actions import Memo
from app.models.dd import Claim, Document, Verification
from app.models.enums import (
    DDItemKind,
    DocumentOrigin,
    ReliabilityTier,
    RunKind,
    SnapshotTrigger,
    SourceKind,
    SubjectType,
    VerificationResult,
)
from app.models.evidence import Fact, Source
from app.models.runs import Job
from app.models.search import Candidate, ScoreSnapshot
from app.services import clients
from app.services.actions import memo, memo_job
from app.services.jobs import queue
from app.services.jobs.registry import HANDLERS
from app.services.jobs.steps import StepRunner
from tests.test_candidates_routes import _fact, _setup

EVIDENCE: dict[str, dict[str, Any]] = {
    "f:1": {"value": 1425, "as_of": "2026-10-01"},
    "f:2": {"value": {"amount_usd": 9000000, "round": "seed"}, "as_of": "2026-08-14"},
    "f:3": {"value": "90% gross retention", "as_of": None},
    "c:abc": {"value": 60, "as_of": "2026-09-30"},
}


def _check(sentence: str) -> str | None:
    return memo.check_sentence(sentence, EVIDENCE)


def test_supported_numbers_and_dates_are_kept() -> None:
    assert _check("Headcount reached 1,425 [f:1].") is None
    assert _check("They raised $9M in Aug 2026 [f:2].") is None
    assert _check("They raised 9 million on 2026-08-14 [f:2].") is None
    assert _check("Headcount as of Oct 2026 was 1425 [f:1].") is None
    assert _check("Retention is 90% [f:3].") is None
    assert _check("The deck claims 60 staff and 1,425 on LinkedIn [c:abc][f:1].") is None
    assert _check("The founder says the team is strong [c:abc].") is None
    assert _check("Strong team, no numbers.") is None


def test_unsupported_sentences_fail() -> None:
    assert "61" in (_check("Headcount reached 61 [f:1].") or "")
    assert "without a citation" in (_check("Headcount reached 1,425.") or "")
    assert "f:999" in (_check("A strong team [f:999].") or "")
    assert _check("They raised $9.5M [f:2].") is not None
    assert _check("They raised $9M in Sep 2026 [f:2].") is not None
    assert _check("They raised $9M on 2026-08-15 [f:2].") is not None
    # the number has to be in the item it cites, not anywhere in the evidence
    assert _check("Headcount reached 1,425 [f:2].") is not None


def test_extract_normalises() -> None:
    tokens = memo.extract("$9M, 1,425 staff, 90%, 2.5 crore, Aug 12, 2026 and 3 Mar 2025")
    assert [n for n, _, _ in tokens.numbers] == [9e6, 1425, 90, 2.5e7]
    assert sorted(tokens.dates) == ["2025-03-03", "2026-08-12"]


def test_post_check_and_refs() -> None:
    draft = ("## Team\n\n- Headcount is 1,425 [f:1]. Planted 7,000 users [f:1].\n"
             "## Funding history\n\nSeed of $9M [f:2]. Unknown 42 [f:9].")
    kept, removed = memo.post_check(draft, EVIDENCE)
    assert kept == ("## Team\n\n- Headcount is 1,425 [f:1].\n"
                    "## Funding history\n\nSeed of $9M [f:2].")
    assert [r["text"] for r in removed] == ["Planted 7,000 users [f:1].", "Unknown 42 [f:9]."]
    markdown, used = memo.render_refs(kept + " Again [f:1][f:2].")
    assert used == ["f:1", "f:2"]
    assert "1,425 [1]" in markdown and "$9M [2]" in markdown and "Again [1][2]" in markdown


# --- the job and the routes ------------------------------------------------------------

def _seed(db: Session) -> tuple[uuid.UUID, Candidate, Fact, Claim]:
    investor, candidate, source, company = _setup(db)
    funding = _fact(db, source, SubjectType.company, company.id, "funding_round",
                    {"amount_usd": 9000000}, date(2026, 8, 14))
    deck_src = Source(kind=SourceKind.upload, endpoint_or_url="deck.pdf",
                      reliability_tier=ReliabilityTier.c)
    db.add(deck_src)
    db.flush()
    doc = Document(candidate_id=candidate.id, kind=DDItemKind.deck, origin=DocumentOrigin.vc_upload,
                   storage_path="x", mime="application/pdf", sha256="0" * 64,
                   source_id=deck_src.id)
    db.add(doc)
    db.flush()
    claim = Claim(candidate_id=candidate.id, document_id=doc.id, page=4, quote="A team of 60",
                  predicate="headcount", value=60, as_of=date(2026, 9, 30))
    db.add(claim)
    db.flush()
    db.add(Verification(claim_id=claim.id, result=VerificationResult.contradicted,
                        fact_ids=[], note="LinkedIn says 26"))
    db.commit()
    return investor.id, candidate, funding, claim


def _run(db: Session, candidate: Candidate, investor_id: uuid.UUID, llm: FakeLLM,
         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memo_job, "clients_for_run", lambda run_id: clients.clients_for_run(
        run_id, llm_transport=llm))
    run = queue.create_run(db, RunKind.memo, {})
    db.commit()
    HANDLERS["memo"](db, StepRunner(db, run.id), {
        "candidate_id": str(candidate.id), "investor_id": str(investor_id)})


def test_job_removes_planted_number_and_versions(
    db: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    investor_id, candidate, funding, claim = _seed(db)
    draft = (f"## Summary\n\nSeed round of $9M in Aug 2026 [f:{funding.id}]. "
             f"Revenue is $3M ARR [f:{funding.id}].\n\n## Team\n\n"
             f"The deck claims 60 people, which LinkedIn contradicts [c:{claim.id}].")
    llm = FakeLLM(draft, "## Summary\n\nCan't verify traction.")
    _run(db, candidate, investor_id, llm, monkeypatch)
    prompt = llm.requests[0]["messages"][-1]["content"]
    assert f"[f:{funding.id}]" in prompt and f"[c:{claim.id}]" in prompt
    assert "contradicted" in prompt

    first = db.scalars(select(Memo)).one()
    headers = {"X-Investor-Id": str(investor_id)}
    body = client.get(f"/memos/{first.id}", headers=headers).json()
    assert body["version"] == 1 and body["stale"] is False
    assert "$3M" not in body["markdown"] and "$9M in Aug 2026 [1]" in body["markdown"]
    assert "60 people, which LinkedIn contradicts [2]" in body["markdown"]
    assert body["removed"] == [{"text": f"Revenue is $3M ARR [f:{funding.id}].",
                                "reason": "unsupported: $3M not in the cited evidence"}]
    [f_cite, c_cite] = body["citations"]
    assert f_cite["ref"] == 1 and f_cite["fact_id"] == funding.id
    assert c_cite["claim_id"] == str(claim.id) and c_cite["citation"]["locator"]["page"] == 4

    _run(db, candidate, investor_id, llm, monkeypatch)
    db.expire_all()
    memos = db.scalars(select(Memo).order_by(Memo.version)).all()
    assert [(m.version, m.stale) for m in memos] == [(1, True), (2, False)]
    assert client.get(f"/candidates/{candidate.id}", headers=headers).json()[
        "latest_memo_id"] == str(memos[1].id)
    assert client.get(f"/memos/{first.id}",
                      headers={"X-Investor-Id": str(uuid.uuid4())}).status_code == 404


def test_request_is_idempotent_per_snapshot(db: Session, client: TestClient) -> None:
    investor_id, candidate, _, _ = _seed(db)
    headers = {"X-Investor-Id": str(investor_id)}
    url = f"/candidates/{candidate.id}/memo"
    first = client.post(url, headers=headers)
    assert first.status_code == 202
    assert client.post(url, headers=headers).json()["run_id"] == first.json()["run_id"]
    db.add(ScoreSnapshot(candidate_id=candidate.id, breakdown=[], delta=[],
                         trigger=SnapshotTrigger.override))
    db.commit()
    assert client.post(url, headers=headers).json()["run_id"] != first.json()["run_id"]
    assert {j.kind for j in db.scalars(select(Job))} == {"memo"}
    assert client.post(url, headers={"X-Investor-Id": str(uuid.uuid4())}).status_code == 404
