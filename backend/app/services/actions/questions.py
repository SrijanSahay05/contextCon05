"""Follow-up questions from gaps, red flags and contradicted claims.

The LLM writes the wording; every question must point at an item we listed, or it's dropped.
"""

import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import SignalKind, VerificationResult
from app.models.search import Question, Signal
from app.repositories import scores
from app.services.clients import Clients

SYSTEM = (
    "You write follow-up questions a venture investor will send to a startup's founders. "
    "For each listed item write exactly one short, specific question that asks for "
    "concrete evidence (a document, a number, a list) that would settle it. Quote the "
    "numbers and dates given. Set motivated_by to the item's type and id exactly as listed."
)


class _Ref(BaseModel):
    type: Literal["signal", "claim"]
    id: str


class _Draft(BaseModel):
    motivated_by: _Ref
    text: str


class _Drafts(BaseModel):
    questions: list[_Draft]


def _items(db: Session, candidate_id: uuid.UUID) -> dict[tuple[str, str], str]:
    """(type, id) → what the question should address."""
    out: dict[tuple[str, str], str] = {}
    for s in db.scalars(select(Signal).where(
            Signal.candidate_id == candidate_id,
            Signal.kind.in_([SignalKind.gap, SignalKind.red_flag]))
            .order_by(Signal.created_at, Signal.id)):
        out[("signal", str(s.id))] = f"{s.kind}: {s.text}"
    for c, v in scores.claims_with_verification(db, candidate_id):
        if v is not None and v.result == VerificationResult.contradicted:
            out[("claim", str(c.id))] = (f"founder claim contradicted by public data: "
                                         f"{c.predicate} = {c.value} ({c.quote!r}); {v.note or ''}")
    return out


def generate_questions(db: Session, clients: Clients, candidate_id: uuid.UUID
                       ) -> list[Question]:
    """Adds draft questions for items that have none yet; returns the new ones. Flushes."""
    taken = {(q.motivated_by.get("type"), q.motivated_by.get("id")) for q in
             db.scalars(select(Question).where(Question.candidate_id == candidate_id))}
    items = {k: v for k, v in _items(db, candidate_id).items() if k not in taken}
    if not items:
        return []
    prompt = "\n".join(f"- type={t} id={i}: {text}" for (t, i), text in items.items())
    drafts = clients.llm.extract(_Drafts, SYSTEM, f"Items:\n{prompt}")
    new: list[Question] = []
    for d in drafts.questions:
        key = (d.motivated_by.type, d.motivated_by.id)
        if key not in items or key in taken or not d.text.strip():
            continue  # orphan, duplicate or empty
        taken.add(key)
        new.append(Question(candidate_id=candidate_id, text=d.text.strip(),
                            motivated_by={"type": key[0], "id": key[1]}))
    db.add_all(new)
    db.flush()
    return new
