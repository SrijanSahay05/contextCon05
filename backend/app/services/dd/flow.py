"""Start a DD round, approve and mark-send its request email, and build the DD view.

Flushes; the route commits.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.errors import ApiError, ErrorCode
from app.integrations.errors import LLMError
from app.models.actions import Outreach
from app.models.dd import DDItem, DDRequest
from app.models.entities import Company
from app.models.enums import (
    CandidateStatus,
    DDStage,
    OutreachChannel,
    OutreachStatus,
    QuestionStatus,
    SignalKind,
)
from app.models.identity import Investor
from app.models.search import Candidate, Question, Search, Signal
from app.repositories import dd as repo
from app.repositories import scores
from app.schemas.dd import DDItemOut, DDOut
from app.schemas.outreach import OutreachOut
from app.services.clients import clients_for_run
from app.services.dd.gaps import LABELS, gap_items

MAX_ROUNDS = 2
STARTABLE = (CandidateStatus.new, CandidateStatus.shortlist, CandidateStatus.watch)
SYSTEM = (
    "You write a short, warm email from a venture investor to a startup founder. Ask for a "
    "30-minute call, then list the requested documents as bullets (one line each, say why "
    "briefly), then the questions. Plain text, no subject line, no placeholders, sign off "
    "with the investor's name."
)


def _not_allowed(message: str, **details: object) -> ApiError:
    return ApiError(409, ErrorCode.not_allowed, message, dict(details))


def _draft_body(investor: str, company: str, items: list[tuple[str, str]],
                questions: list[str]) -> str:
    lines = "\n".join(f"- {label} ({reason})" for label, reason in items)
    asks = "\n".join(f"- {q}" for q in questions)
    prompt = (f"Investor: {investor}\nCompany: {company}\n\nRequested items:\n{lines}\n\n"
              f"Questions:\n{asks or '(none)'}")
    try:
        body = clients_for_run(None).llm.write(SYSTEM, prompt)
    except LLMError:
        body = ""
    # no LLM (or it failed): a plain template the partner edits before approving
    return body.strip() or (
        f"Hi,\n\nThanks for your time so far. Could we find 30 minutes for a call next "
        f"week? To prepare, could you share:\n{lines}\n"
        + (f"\nA few questions:\n{asks}\n" if asks else "") + f"\nBest,\n{investor}"
    )


def start(db: Session, candidate: Candidate) -> DDRequest:
    previous = repo.latest_request(db, candidate.id)
    second_round = (candidate.status == CandidateStatus.in_dd
                    and candidate.dd_stage == DDStage.ready_for_decision)
    if candidate.status not in STARTABLE and not second_round:
        raise _not_allowed(f"Cannot start DD from {candidate.status} / {candidate.dd_stage}",
                           status=candidate.status, dd_stage=candidate.dd_stage)
    round_no = previous.round + 1 if previous else 1
    if round_no > MAX_ROUNDS:
        raise ApiError(409, ErrorCode.conflict, f"At most {MAX_ROUNDS} DD request rounds",
                       {"round": round_no})

    candidate.status = CandidateStatus.in_dd
    candidate.dd_stage = DDStage.gaps_identified
    request = DDRequest(candidate_id=candidate.id, round=round_no)
    db.add(request)
    db.flush()

    gap_texts = list(db.scalars(select(Signal.text).where(
        Signal.candidate_id == candidate.id, Signal.kind == SignalKind.gap)))
    wanted = gap_items(candidate.breakdown, gap_texts, scores.has_deck(db, candidate.id))
    db.add_all(DDItem(dd_request_id=request.id, kind=k, reason=r) for k, r in wanted)

    search = db.get(Search, candidate.search_id)
    company = db.get(Company, candidate.company_id)
    assert search is not None and company is not None  # non-null FKs
    investor = db.get(Investor, search.investor_id)
    questions = list(db.scalars(select(Question.text).where(
        Question.candidate_id == candidate.id, Question.status == QuestionStatus.draft)))
    investor_name = investor.name if investor else "the team"
    db.add(Outreach(
        candidate_id=candidate.id, dd_request_id=request.id, channel=OutreachChannel.email,
        subject=f"{investor_name} <> {company.name}: a few documents",
        body=_draft_body(investor_name, company.name,
                         [(LABELS[k], r) for k, r in wanted], questions),
        idempotency_key=f"dd:{request.id}",
    ))
    candidate.dd_stage = DDStage.request_drafted
    db.flush()
    return request


def _outreach(db: Session, request: DDRequest) -> Outreach:
    outreach = repo.request_outreach(db, request.id)
    if outreach is None:
        raise ApiError(404, ErrorCode.not_found, "This DD request has no email draft")
    return outreach


def approve(db: Session, request: DDRequest, investor_id: uuid.UUID) -> None:
    outreach = _outreach(db, request)
    if outreach.status == OutreachStatus.draft:
        outreach.status = OutreachStatus.approved
        outreach.approved_by = investor_id
        outreach.approved_at = datetime.now(timezone.utc)
        db.flush()


def mark_sent(db: Session, request: DDRequest) -> None:
    outreach = _outreach(db, request)
    if outreach.status == OutreachStatus.draft:
        raise _not_allowed("Approve the request email before sending it",
                           outreach_status=outreach.status)
    if outreach.status != OutreachStatus.approved:
        return  # already sent: idempotent
    outreach.status = OutreachStatus.sent
    outreach.sent_at = datetime.now(timezone.utc)
    candidate = db.get(Candidate, request.candidate_id)
    assert candidate is not None  # non-null FK
    candidate.dd_stage = DDStage.awaiting_founder
    db.flush()


def dd_out(db: Session, request: DDRequest) -> DDOut:
    candidate = db.get(Candidate, request.candidate_id)
    assert candidate is not None  # non-null FK
    outreach = repo.request_outreach(db, request.id)
    claims = [scores._claim_out(db, c, v)
              for c, v in scores.claims_with_verification(db, candidate.id)]
    settings = get_settings()
    waiting = candidate.dd_stage == DDStage.awaiting_founder
    since = outreach.sent_at if outreach and waiting else None
    return DDOut(
        request_id=request.id, candidate_id=candidate.id, round=request.round,
        stage=candidate.dd_stage or DDStage.gaps_identified,
        request=OutreachOut.model_validate(outreach, from_attributes=True) if outreach else None,
        items=[DDItemOut(id=i.id, kind=i.kind, status=i.status, label=LABELS[i.kind],
                         document_id=i.document_id,
                         satisfied_by_message_id=i.satisfied_by_message_id)
               for i in repo.items(db, request.id)],
        claims=claims,
        verifications=[c.verification for c in claims if c.verification is not None],
        thread=None,  # Gmail threads arrive with the Gmail track
        score_history=scores.candidate_out(db, candidate).score_history,
        reminder_due_at=since + timedelta(days=settings.dd_reminder_days) if since else None,
        timeout_at=since + timedelta(days=settings.dd_timeout_days) if since else None,
    )
