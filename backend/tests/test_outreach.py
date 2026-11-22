import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.llm import FakeLLM
from app.models.enums import QuestionStatus, SignalKind
from app.models.identity import Fund
from app.models.search import Candidate, Question, Signal
from app.services import clients
from app.services.actions import outreach
from app.services.scoring.service import score_candidate
from tests.test_candidates_routes import _setup

HOOK = "Launch"  # the fixture's latest dated news item


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr(outreach, "clients_for_run",
                        lambda run_id: clients.clients_for_run(run_id, llm_transport=fake))
    return fake


def _scored(db: Session) -> tuple[dict[str, str], Candidate, Signal]:
    investor, candidate, _, _ = _setup(db)
    fund = Fund(name="Kestrel Ventures")
    db.add(fund)
    db.flush()
    investor.fund_id = fund.id
    score_candidate(db, candidate.id)
    gap = db.scalars(select(Signal).where(Signal.candidate_id == candidate.id,
                                          Signal.kind == SignalKind.gap)).first()
    assert gap is not None
    db.commit()
    return {"X-Investor-Id": str(investor.id)}, candidate, gap


def test_email_draft_cites_a_real_fact_and_generates_questions(
        client: TestClient, db: Session, llm: FakeLLM) -> None:
    headers, candidate, gap = _scored(db)
    llm.queue({"questions": [{"motivated_by": {"type": "signal", "id": str(gap.id)},
                              "text": "Could you share your funding history?"}]},
              f"Hi Asha, congrats on the {HOOK}! Could you share your funding history?")

    response = client.post(f"/candidates/{candidate.id}/outreach",
                           json={"channel": "email", "purpose": "call_request"}, headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft" and HOOK in body["body"]
    assert body["subject"] == "Kestrel Ventures <> Acme"
    prompt = llm.requests[-1]["messages"][1]["content"]
    assert "Kestrel Ventures" in prompt and f"Hook (recent, from public data): {HOOK}" in prompt
    assert "Could you share your funding history?" in prompt and "deck" in prompt
    questions = client.get(f"/candidates/{candidate.id}", headers=headers).json()["questions"]
    assert [q["motivated_by"] for q in questions] == [{"type": "signal", "id": str(gap.id)}]


def test_linkedin_draft_is_regenerated_then_trimmed(
        client: TestClient, db: Session, llm: FakeLLM) -> None:
    headers, candidate, gap = _scored(db)
    db.add(Question(candidate_id=candidate.id, text="Funding?",
                    motivated_by={"type": "signal", "id": str(gap.id)}))
    db.commit()
    llm.queue("word " * 100, "word " * 100)  # too long and no hook, twice

    response = client.post(f"/candidates/{candidate.id}/outreach",
                           json={"channel": "linkedin", "purpose": "follow_up"}, headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert len(body["body"]) <= 300 and HOOK in body["body"] and body["subject"] is None
    assert len(llm.requests) == 2 and "Rewrite:" in llm.requests[1]["messages"][1]["content"]


def test_lifecycle_and_scope(client: TestClient, db: Session, llm: FakeLLM) -> None:
    headers, candidate, gap = _scored(db)
    db.add(Question(candidate_id=candidate.id, text="Funding?",
                    motivated_by={"type": "signal", "id": str(gap.id)}))
    db.commit()
    llm.queue(f"Saw the {HOOK}. Can we talk?")
    oid = client.post(f"/candidates/{candidate.id}/outreach",
                      json={"channel": "email", "purpose": "call_request"},
                      headers=headers).json()["id"]
    url = f"/outreach/{oid}"

    early = client.post(f"{url}/mark-sent", headers=headers)
    assert early.status_code == 409 and early.json()["error"]["code"] == "not_allowed"

    assert client.put(url, json={"body": "Edited"}, headers=headers).json()["body"] == "Edited"
    approved = client.post(f"{url}/approve", headers=headers).json()
    assert approved["status"] == "approved" and approved["approved_at"]
    assert approved["approved_by"] == headers["X-Investor-Id"]
    assert db.scalars(select(Question.status)).all() == [QuestionStatus.approved]

    # editing approved text sends it back for approval
    edited = client.put(url, json={"subject": "New"}, headers=headers).json()
    assert edited["status"] == "draft" and edited["approved_by"] is None
    client.post(f"{url}/approve", headers=headers)

    sent = client.post(f"{url}/mark-sent", headers=headers)
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    again = client.post(f"{url}/mark-sent", headers=headers)
    assert again.status_code == 200 and again.json() == sent.json()
    db.expire_all()
    assert db.scalars(select(Question.status)).all() == [QuestionStatus.sent]
    assert client.put(url, json={"body": "x"}, headers=headers).status_code == 409
    assert client.post(f"{url}/approve", headers=headers).status_code == 409
    assert client.post(f"{url}/send", headers=headers).status_code == 501

    other = {"X-Investor-Id": str(uuid.uuid4())}
    calls: list[tuple[str, str, dict[str, Any]]] = [
        ("POST", f"/candidates/{candidate.id}/outreach",
         {"json": {"channel": "email", "purpose": "call_request"}}),
        ("PUT", url, {"json": {"body": "x"}}),
        ("POST", f"{url}/approve", {}), ("POST", f"{url}/send", {}),
        ("POST", f"{url}/mark-sent", {}),
    ]
    for method, path, kw in calls:
        assert client.request(method, path, headers=other, **kw).status_code == 404, path
