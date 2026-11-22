import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.integrations.llm import FakeLLM
from app.models.entities import Company
from app.models.enums import CandidateStatus, DDStage, QuestionStatus
from app.models.identity import Investor
from app.models.search import Candidate, Question, Search
from app.services import clients
from app.services.dd import flow
from app.services.scoring.service import score_candidate


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr(flow, "clients_for_run",
                        lambda run_id: clients.clients_for_run(run_id, llm_transport=fake))
    return fake


def _setup(db: Session, status: CandidateStatus = CandidateStatus.shortlist
           ) -> tuple[dict[str, str], Candidate]:
    investor = Investor(name="Ananya")
    company = Company(crustdata_company_id=501, name="Ledgerline")
    db.add_all([investor, company])
    db.flush()
    search = Search(investor_id=investor.id, query_text="fintech", parsed_filters={},
                    unresolved=[], as_of=date(2026, 11, 1))
    db.add(search)
    db.flush()
    candidate = Candidate(search_id=search.id, company_id=company.id, breakdown=[],
                          status=status)
    db.add(candidate)
    db.flush()
    db.add(Question(candidate_id=candidate.id, text="Who leads engineering?",
                    motivated_by={"type": "gap", "id": "team"},
                    status=QuestionStatus.draft))
    score_candidate(db, candidate.id)  # no facts: every criterion unknown → gap signals
    db.commit()
    return {"X-Investor-Id": str(investor.id)}, candidate


def test_start_dd_drafts_items_and_request(client: TestClient, db: Session,
                                           llm: FakeLLM) -> None:
    headers, candidate = _setup(db)
    llm.queue("Hi Rohan, could we talk next week?")

    response = client.post(f"/candidates/{candidate.id}/dd", headers=headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["round"] == 1 and body["stage"] == "request_drafted"
    kinds = {i["kind"] for i in body["items"]}
    assert {"deck", "financials", "data_room", "answer", "cap_table", "grant_letter",
            "customer_refs"} <= kinds
    assert all(i["status"] == "requested" for i in body["items"])
    request = body["request"]
    assert request["status"] == "draft" and request["dd_request_id"] == body["request_id"]
    assert request["body"] == "Hi Rohan, could we talk next week?"
    prompt = llm.requests[0]["messages"][1]["content"]
    assert "Latest pitch deck" in prompt and "Who leads engineering?" in prompt
    db.refresh(candidate)
    assert candidate.status == CandidateStatus.in_dd

    got = client.get(f"/candidates/{candidate.id}/dd", headers=headers)
    assert got.status_code == 200 and got.json()["request_id"] == body["request_id"]
    assert len(got.json()["score_history"]) == 1


def test_approve_and_mark_sent_lifecycle(client: TestClient, db: Session,
                                         llm: FakeLLM) -> None:
    headers, candidate = _setup(db)
    llm.queue("Draft")
    request_id = client.post(f"/candidates/{candidate.id}/dd", headers=headers).json()[
        "request_id"]

    early = client.post(f"/dd/{request_id}/mark-sent", headers=headers)
    assert early.status_code == 409 and early.json()["error"]["code"] == "not_allowed"

    approved = client.post(f"/dd/{request_id}/approve", headers=headers).json()
    assert approved["request"]["status"] == "approved"
    assert approved["request"]["approved_by"] == headers["X-Investor-Id"]

    sent = client.post(f"/dd/{request_id}/mark-sent", headers=headers)
    assert sent.status_code == 200
    body = sent.json()
    assert body["stage"] == "awaiting_founder" and body["request"]["status"] == "sent"
    assert body["reminder_due_at"] and body["timeout_at"]
    again = client.post(f"/dd/{request_id}/mark-sent", headers=headers).json()
    assert again["request"]["sent_at"] == body["request"]["sent_at"]  # idempotent

    assert client.post(f"/dd/{request_id}/send", headers=headers).status_code == 501
    # a second round only once the first is ready for a decision
    assert client.post(f"/candidates/{candidate.id}/dd", headers=headers).status_code == 409


def _ready(db: Session, candidate: Candidate) -> None:
    db.refresh(candidate)  # the route changed it in another session
    candidate.dd_stage = DDStage.ready_for_decision
    db.commit()


def test_round_limit(client: TestClient, db: Session, llm: FakeLLM) -> None:
    headers, candidate = _setup(db)
    llm.queue("Round one", "Round two")
    assert client.post(f"/candidates/{candidate.id}/dd", headers=headers).status_code == 201
    _ready(db, candidate)
    second = client.post(f"/candidates/{candidate.id}/dd", headers=headers)
    assert second.status_code == 201 and second.json()["round"] == 2
    _ready(db, candidate)
    third = client.post(f"/candidates/{candidate.id}/dd", headers=headers)
    assert third.status_code == 409 and third.json()["error"]["code"] == "conflict", third.text


def test_wrong_status_and_scoping(client: TestClient, db: Session, llm: FakeLLM) -> None:
    headers, candidate = _setup(db, CandidateStatus.pass_)
    assert client.post(f"/candidates/{candidate.id}/dd", headers=headers).status_code == 409

    candidate.status = CandidateStatus.watch
    db.commit()
    llm.queue("Draft")
    request_id = client.post(f"/candidates/{candidate.id}/dd", headers=headers).json()[
        "request_id"]
    other = {"X-Investor-Id": str(uuid.uuid4())}
    assert client.get(f"/candidates/{candidate.id}/dd", headers=other).status_code == 404
    assert client.post(f"/candidates/{candidate.id}/dd", headers=other).status_code == 404
    for action in ("approve", "send", "mark-sent"):
        assert client.post(f"/dd/{request_id}/{action}", headers=other).status_code == 404


def test_get_dd_before_start_is_404(client: TestClient, db: Session) -> None:
    headers, candidate = _setup(db)
    assert client.get(f"/candidates/{candidate.id}/dd", headers=headers).status_code == 404
