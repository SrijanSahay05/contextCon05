"""Outreach drafts and their lifecycle: draft → approved → sent (by hand for now).

Nothing leaves Scout without the partner's approval. Gmail sending is not built yet.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.integrations.errors import LLMError
from app.integrations.llm import quote_check
from app.models.actions import Outreach
from app.models.entities import Company
from app.models.enums import OutreachChannel, OutreachStatus, QuestionStatus, SubjectType
from app.models.evidence import Fact
from app.models.identity import Fund, Investor
from app.models.search import Question
from app.repositories import outreach as repo
from app.repositories import scores
from app.schemas.outreach import OutreachCreate, OutreachEdit
from app.services.actions.questions import generate_questions
from app.services.clients import Clients, clients_for_run
from app.services.evidence import facts_mapper as fm

LINKEDIN_LIMIT = 300
HOOK_PREDICATES = (fm.FUNDING_ROUND, fm.NEWS_ITEM, fm.LAST_ROUND_DATE, fm.HEADCOUNT_AT)
PURPOSES = {
    "call_request": "Ask for a 30-minute intro call and for their latest deck.",
    "follow_up": "Politely follow up on an earlier message that got no reply.",
}
SYSTEM = (
    "You write short, warm, specific outreach from a venture investor to a startup founder. "
    "Plain text only, no subject line, no placeholders like [Name]. Open with the hook "
    "given, using its exact wording. Never invent facts beyond what is given."
)


def _hook(db: Session, company_id: uuid.UUID) -> str | None:
    """The most recent dated fact worth opening with, as short text that must appear."""
    fact = db.scalars(select(Fact).where(
        Fact.subject_type == SubjectType.company, Fact.subject_id == company_id,
        Fact.predicate.in_(HOOK_PREDICATES), Fact.as_of.is_not(None),
    ).order_by(Fact.as_of.desc(), Fact.id.desc()).limit(1)).first()
    if fact is None:
        return None
    v: Any = fact.value
    if fact.predicate == fm.FUNDING_ROUND:
        return f"{v.get('round_type') or 'funding'} round"
    if fact.predicate == fm.NEWS_ITEM:
        return str(v.get("title") or v.get("headline") or "") or None
    if fact.predicate == fm.HEADCOUNT_AT:
        return f"{v} people"
    return f"round on {v}"


def _firm(db: Session, investor_id: uuid.UUID) -> tuple[str, str]:
    investor = db.get(Investor, investor_id)
    assert investor is not None  # owns the candidate
    fund = db.get(Fund, investor.fund_id) if investor.fund_id else None
    return investor.name, fund.name if fund else investor.name


def _fits(body: str, hook: str | None, channel: OutreachChannel) -> str:
    """Why `body` fails the checks, or ''."""
    if hook and not quote_check(body, hook):
        return f"it must mention {hook!r} verbatim"
    if channel == OutreachChannel.linkedin and len(body) > LINKEDIN_LIMIT:
        return f"it is {len(body)} characters; LinkedIn allows {LINKEDIN_LIMIT}"
    return ""


def _draft(clients: Clients, prompt: str, hook: str | None, channel: OutreachChannel) -> str:
    body, why = "", ""
    for _ in range(2):  # regenerate once with the reason
        body = clients.llm.write(SYSTEM, prompt + (f"\n\nRewrite: {why}." if why else "")).strip()
        why = _fits(body, hook, channel)
        if not why:
            return body
    if hook and not quote_check(body, hook):
        body = f"Saw the news: {hook}. {body}"
    if channel == OutreachChannel.linkedin and len(body) > LINKEDIN_LIMIT:
        body = body[:LINKEDIN_LIMIT - 1].rsplit(" ", 1)[0] + "…"
    return body


def create(db: Session, investor_id: uuid.UUID, candidate_id: uuid.UUID,
           body: OutreachCreate) -> Outreach:
    candidate = scores.get_owned(db, candidate_id, investor_id)
    company = db.get(Company, candidate.company_id)
    assert company is not None  # non-null FK
    clients = clients_for_run(None)
    try:
        if db.scalar(select(Question.id).where(Question.candidate_id == candidate.id)
                     .limit(1)) is None:
            generate_questions(db, clients, candidate.id)
        questions = db.scalars(select(Question).where(
            Question.candidate_id == candidate.id,
            Question.status.in_([QuestionStatus.draft, QuestionStatus.approved]))).all()
        partner, firm = _firm(db, investor_id)
        founders = [p.name for p, _ in scores.founders(db, company.id)]
        hook = _hook(db, company.id)
        limit = (f"At most {LINKEDIN_LIMIT} characters in total; include at most one question."
                 if body.channel == OutreachChannel.linkedin else "Under 150 words.")
        prompt = "\n".join([
            f"Channel: {body.channel}. {limit}",
            f"From: {partner}, {firm}",
            f"To: {', '.join(founders) or 'the founders'} of {company.name}",
            f"Hook (recent, from public data): {hook}" if hook else "Hook: none; keep it general.",
            f"Purpose: {PURPOSES[body.purpose]}",
            "Questions to include:" if questions else "",
            *(f"- {q.text}" for q in questions),
        ])
        text = _draft(clients, prompt, hook, body.channel)
    except LLMError as exc:
        raise ApiError(503, ErrorCode.upstream_unavailable, "The LLM is unavailable",
                       {"reason": str(exc)[:300]}) from exc
    row = Outreach(
        candidate_id=candidate.id, channel=body.channel, body=text,
        subject=f"{firm} <> {company.name}" if body.channel == OutreachChannel.email else None,
        status=OutreachStatus.draft, idempotency_key=uuid.uuid4().hex,
    )
    db.add(row)
    db.flush()
    return row


def _wrong_status(row: Outreach, action: str) -> ApiError:
    return ApiError(409, ErrorCode.not_allowed,
                    f"Cannot {action} an outreach that is '{row.status}'",
                    {"status": str(row.status)})


def edit(db: Session, investor_id: uuid.UUID, outreach_id: uuid.UUID,
         body: OutreachEdit) -> Outreach:
    row = repo.get_owned(db, outreach_id, investor_id)
    if row.status not in (OutreachStatus.draft, OutreachStatus.approved):
        raise _wrong_status(row, "edit")
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(row, field, value)
    # changed text needs a fresh approval
    row.status, row.approved_by, row.approved_at = OutreachStatus.draft, None, None
    db.flush()
    return row


def _set_questions(db: Session, candidate_id: uuid.UUID, old: QuestionStatus,
                   new: QuestionStatus) -> None:
    for q in db.scalars(select(Question).where(Question.candidate_id == candidate_id,
                                               Question.status == old)):
        q.status = new


def approve(db: Session, investor_id: uuid.UUID, outreach_id: uuid.UUID) -> Outreach:
    row = repo.get_owned(db, outreach_id, investor_id)
    if row.status == OutreachStatus.approved:
        return row
    if row.status != OutreachStatus.draft:
        raise _wrong_status(row, "approve")
    row.status, row.approved_by, row.approved_at = (
        OutreachStatus.approved, investor_id, datetime.now(UTC))
    _set_questions(db, row.candidate_id, QuestionStatus.draft, QuestionStatus.approved)
    db.flush()
    return row


def mark_sent(db: Session, investor_id: uuid.UUID, outreach_id: uuid.UUID) -> Outreach:
    row = repo.get_owned(db, outreach_id, investor_id)
    if row.status == OutreachStatus.sent:
        return row  # idempotent: a double click changes nothing
    if row.status != OutreachStatus.approved:
        raise _wrong_status(row, "mark as sent")
    row.status, row.sent_at = OutreachStatus.sent, datetime.now(UTC)
    _set_questions(db, row.candidate_id, QuestionStatus.approved, QuestionStatus.sent)
    db.flush()
    return row
