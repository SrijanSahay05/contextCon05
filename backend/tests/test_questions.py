from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.llm import FakeLLM
from app.models.dd import Claim, Verification
from app.models.enums import QuestionStatus, SignalKind, VerificationResult
from app.models.search import Question, Signal
from app.services import clients
from app.services.actions.questions import generate_questions
from app.services.scoring.service import score_candidate
from tests.test_candidates_routes import _setup


def test_questions_need_a_real_motivation_and_never_duplicate(db: Session) -> None:
    _, candidate, _, _ = _setup(db)
    claim = Claim(candidate_id=candidate.id, quote="team of 60", predicate="headcount",
                  value=60, as_of=date(2026, 10, 1))
    db.add(claim)
    db.flush()
    db.add(Verification(claim_id=claim.id, result=VerificationResult.contradicted,
                        fact_ids=[], note="public headcount is 26"))
    score_candidate(db, candidate.id)
    gap = db.scalars(select(Signal).where(Signal.candidate_id == candidate.id,
                                          Signal.kind == SignalKind.gap)).first()
    strong = db.scalars(select(Signal).where(Signal.candidate_id == candidate.id,
                                             Signal.kind == SignalKind.strong)).first()
    assert gap is not None and strong is not None

    def ask(sig: str, text: str, kind: str = "signal") -> dict[str, object]:
        return {"motivated_by": {"type": kind, "id": sig}, "text": text}

    llm = FakeLLM({"questions": [
        ask(str(gap.id), "Can you share your funding history?"),
        ask(str(gap.id), "Same gap again?"),                       # duplicate
        ask(str(claim.id), "Your deck says 60; can you share the team list?", "claim"),
        ask("00000000-0000-0000-0000-000000000000", "Orphan?"),     # not listed
        ask(str(strong.id), "Strong signals are not asked about"),  # not a gap/red flag
    ]})
    c = clients.clients_for_run(None, llm_transport=llm)

    new = generate_questions(db, c, candidate.id)

    assert {(q.motivated_by["type"], q.motivated_by["id"]) for q in new} == {
        ("signal", str(gap.id)), ("claim", str(claim.id))}
    assert all(q.status == QuestionStatus.draft for q in new)
    prompt = llm.requests[0]["messages"][1]["content"]
    assert str(gap.id) in prompt and str(claim.id) in prompt and str(strong.id) not in prompt

    # a second run only offers the items still without a question; repeats are dropped
    llm.queue({"questions": [ask(str(gap.id), "Funding again?")]})
    assert generate_questions(db, c, candidate.id) == []
    assert str(gap.id) not in llm.requests[1]["messages"][1]["content"]
    assert len(db.scalars(select(Question)).all()) == 2
