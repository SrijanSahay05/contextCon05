"""Loading scoring evidence, storing signals and snapshots, and the candidate view."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.actions import Memo
from app.models.dd import Claim, Document, Verification
from app.models.entities import Company, CompanyPerson, Person
from app.models.enums import DDItemKind, ReviewStatus, SubjectType
from app.models.evidence import Fact, Source
from app.models.onboarding import ScoringProfile, Thesis
from app.models.search import Candidate, Question, ScoreSnapshot, Search, Signal
from app.schemas.candidate import (
    CandidateOut,
    CompanyOut,
    CriterionScore,
    FounderOut,
    MotivatedBy,
    OverrideOut,
    QuestionOut,
    ScoreSnapshotOut,
    SignalOut,
)
from app.schemas.common import ClaimOut, VerificationOut
from app.services.evidence import facts_mapper as fm
from app.services.evidence.sources import fact_out
from app.services.scoring.rules import Item


def get_owned(db: Session, candidate_id: uuid.UUID, investor_id: uuid.UUID) -> Candidate:
    row = db.execute(
        select(Candidate).join(Search, Search.id == Candidate.search_id)
        .where(Candidate.id == candidate_id, Search.investor_id == investor_id)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, ErrorCode.not_found, "Candidate not found")
    return row


def founders(db: Session, company_id: uuid.UUID) -> list[tuple[Person, str]]:
    rows = db.execute(
        select(Person, CompanyPerson.role).join(CompanyPerson, CompanyPerson.person_id == Person.id)
        .where(CompanyPerson.company_id == company_id, CompanyPerson.role.ilike("%founder%"))
        .order_by(Person.name)
    ).all()
    return [(p, r) for p, r in rows]


def fact_items(db: Session, company_id: uuid.UUID, person_ids: list[uuid.UUID]) -> list[Item]:
    """The company's facts and its founders' facts, with each source's tier."""
    rows = db.execute(
        select(Fact, Source.reliability_tier).join(Source, Source.id == Fact.source_id).where(
            ((Fact.subject_type == SubjectType.company) & (Fact.subject_id == company_id))
            | ((Fact.subject_type == SubjectType.person) & Fact.subject_id.in_(person_ids))
        ).order_by(Fact.id)
    ).all()
    return [
        Item(f.id, f.predicate, f.value, f.as_of,
             "company" if f.subject_type == SubjectType.company else str(f.subject_id),
             tier=str(tier))
        for f, tier in rows
    ]


def _latest_verifications(db: Session, claim_ids: list[uuid.UUID]) -> dict[uuid.UUID, Verification]:
    rows = db.scalars(select(Verification).where(Verification.claim_id.in_(claim_ids))
                      .order_by(Verification.created_at, Verification.id)).all()
    return {v.claim_id: v for v in rows}  # last one wins


def claims_with_verification(db: Session, candidate_id: uuid.UUID
                             ) -> list[tuple[Claim, Verification | None]]:
    claims = db.scalars(select(Claim).where(Claim.candidate_id == candidate_id)
                        .order_by(Claim.created_at, Claim.id)).all()
    latest = _latest_verifications(db, [c.id for c in claims])
    return [(c, latest.get(c.id)) for c in claims]


def claim_items(db: Session, candidate_id: uuid.UUID) -> list[Item]:
    return [Item(str(c.id), c.predicate, c.value, c.as_of,
                 verification=v.result if v else None)
            for c, v in claims_with_verification(db, candidate_id)]


def profile_for(db: Session, search: Search) -> ScoringProfile | None:
    if search.profile_id:
        return db.get(ScoringProfile, search.profile_id)
    return db.scalars(select(ScoringProfile).where(
        ScoringProfile.investor_id == search.investor_id,
        ScoringProfile.status == ReviewStatus.confirmed,
    ).order_by(ScoringProfile.version.desc()).limit(1)).first()


def thesis_for(db: Session, search: Search) -> Thesis | None:
    if search.thesis_id:
        return db.get(Thesis, search.thesis_id)
    return db.scalars(select(Thesis).where(
        Thesis.investor_id == search.investor_id, Thesis.status == ReviewStatus.confirmed,
    ).order_by(Thesis.version.desc()).limit(1)).first()


def has_deck(db: Session, candidate_id: uuid.UUID) -> bool:
    return db.scalar(select(Document.id).where(
        Document.candidate_id == candidate_id, Document.kind == DDItemKind.deck).limit(1)
    ) is not None


def snapshots(db: Session, candidate_id: uuid.UUID) -> Sequence[ScoreSnapshot]:
    return db.scalars(select(ScoreSnapshot).where(ScoreSnapshot.candidate_id == candidate_id)
                      .order_by(ScoreSnapshot.created_at, ScoreSnapshot.id)).all()


def replace_signals(db: Session, candidate_id: uuid.UUID, drafts: list[Any]) -> None:
    """Keep signals that still hold (same kind and text) so their ids, and the questions
    pointing at them, survive a rescore; drop the rest and add new ones."""
    existing = {(s.kind, s.text): s for s in db.scalars(
        select(Signal).where(Signal.candidate_id == candidate_id))}
    wanted = {(d.kind, d.text): d for d in drafts}
    stale = [s.id for key, s in existing.items() if key not in wanted]
    if stale:
        db.execute(delete(Signal).where(Signal.id.in_(stale)))
    for key, d in wanted.items():
        if key in existing:
            existing[key].fact_ids, existing[key].claim_ids = list(d.fact_ids), list(d.claim_ids)
        else:
            db.add(Signal(candidate_id=candidate_id, kind=d.kind, text=d.text,
                          fact_ids=list(d.fact_ids), claim_ids=list(d.claim_ids)))


# --- the candidate view ---------------------------------------------------------------

def _num(value: Any) -> float | None:
    return float(value) if value is not None else None


def _latest_value(facts: list[Fact], predicate: str) -> Any:
    hits = [f for f in facts if f.predicate == predicate]
    return hits[-1].value if hits else None


def _company_out(db: Session, company: Company) -> CompanyOut:
    facts = sorted(
        db.scalars(select(Fact).where(Fact.subject_type == SubjectType.company,
                                      Fact.subject_id == company.id)).all(),
        key=lambda f: (f.as_of is not None, f.as_of, f.id),
    )
    headcount = _latest_value(facts, fm.HEADCOUNT_TOTAL)
    year = _latest_value(facts, fm.YEAR_FOUNDED)
    return CompanyOut(
        id=company.id, crustdata_company_id=company.crustdata_company_id, name=company.name,
        domain=company.domain, one_liner=_latest_value(facts, fm.DESCRIPTION),
        hq_location=_latest_value(facts, fm.HQ_CITY) or _latest_value(facts, fm.HQ_COUNTRY),
        founded_year=int(year) if isinstance(year, (int, float)) else None,
        headcount=int(headcount) if isinstance(headcount, (int, float)) else None,
        linkedin_url=None,
    )


def _claim_out(db: Session, claim: Claim, ver: Verification | None) -> ClaimOut:
    verification = None
    if ver is not None:
        facts = [f for f in (db.get(Fact, int(i)) for i in ver.fact_ids) if f is not None]
        verification = VerificationOut(
            id=ver.id, claim_id=claim.id, result=ver.result,
            facts=[fact_out(db, f) for f in facts], note=ver.note,
            tolerance_used=ver.tolerance_used, created_at=ver.created_at,
        )
    return ClaimOut(id=claim.id, predicate=claim.predicate, value=claim.value,
                    as_of=claim.as_of, page=claim.page, quote=claim.quote,
                    verification=verification)


def _delta_out(delta: list[Any]) -> dict[str, Any]:
    return {d["key"]: {k: v for k, v in d.items() if k != "key"} for d in delta}


def candidate_out(db: Session, candidate: Candidate) -> CandidateOut:
    company = db.get(Company, candidate.company_id)
    assert company is not None  # non-null FK
    fact_rows = {
        f.id: f for f in db.scalars(select(Fact).where(Fact.id.in_(
            {int(i) for c in candidate.breakdown for i in c.get("fact_ids", [])})))
    }
    claims = {str(c.id): (c, v) for c, v in claims_with_verification(db, candidate.id)}
    breakdown = [
        CriterionScore(
            key=c["key"], score=c["score"], weight=c["weight"], reason=c["reason"],
            facts=[fact_out(db, fact_rows[i]) for i in c.get("fact_ids", []) if i in fact_rows],
            claims=[_claim_out(db, *claims[i]) for i in c.get("claim_ids", []) if i in claims],
        )
        for c in candidate.breakdown
    ]
    signals = db.scalars(select(Signal).where(Signal.candidate_id == candidate.id)
                         .order_by(Signal.created_at, Signal.id)).all()
    questions = db.scalars(select(Question).where(Question.candidate_id == candidate.id)).all()
    history = snapshots(db, candidate.id)
    memo_id = db.scalar(select(Memo.id).where(Memo.candidate_id == candidate.id)
                        .order_by(Memo.version.desc()).limit(1))
    return CandidateOut(
        id=candidate.id, search_id=candidate.search_id, company=_company_out(db, company),
        founders=[
            FounderOut(id=p.id, crustdata_person_id=p.crustdata_person_id, name=p.name,
                       role=role, linkedin_url=p.linkedin_url,
                       headline=_latest_value(list(db.scalars(select(Fact).where(
                           Fact.subject_type == SubjectType.person, Fact.subject_id == p.id,
                           Fact.predicate == fm.HEADLINE).order_by(Fact.id))), fm.HEADLINE))
            for p, role in founders(db, company.id)
        ],
        status=candidate.status, dd_stage=candidate.dd_stage, score=_num(candidate.score),
        completeness=_num(candidate.completeness), profile_version=candidate.profile_version,
        breakdown=breakdown,
        signals=[SignalOut(id=s.id, kind=s.kind, text=s.text, fact_ids=s.fact_ids,
                           claim_ids=s.claim_ids) for s in signals],
        questions=[QuestionOut(id=q.id, text=q.text, status=q.status,
                               motivated_by=MotivatedBy.model_validate(q.motivated_by))
                   for q in questions],
        suggested_action=candidate.suggested_action, suggested_reason=candidate.suggested_reason,
        override=OverrideOut.model_validate(candidate.override) if candidate.override else None,
        score_history=[
            ScoreSnapshotOut(id=s.id, score=_num(s.score), completeness=_num(s.completeness),
                             profile_version=s.profile_version or 0, trigger=s.trigger,
                             delta=_delta_out(s.delta) if n else None, created_at=s.created_at)
            for n, s in enumerate(history)
        ],
        latest_memo_id=memo_id, updated_at=candidate.updated_at,
    )
