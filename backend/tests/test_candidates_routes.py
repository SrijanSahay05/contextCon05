import uuid
from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dd import Claim, Verification
from app.models.entities import Company, CompanyPerson, Person
from app.models.enums import (
    ExtractedBy,
    ReliabilityTier,
    SignalKind,
    SnapshotTrigger,
    SourceKind,
    SubjectType,
    VerificationResult,
)
from app.models.evidence import Fact, Source
from app.models.identity import Investor
from app.models.search import Candidate, ScoreSnapshot, Search, Signal
from app.services.scoring.service import score_candidate, score_search


def _fact(db: Session, source: Source, subject: SubjectType, subject_id: uuid.UUID,
          predicate: str, value: Any, as_of: date | None = None) -> Fact:
    fact = Fact(subject_type=subject, subject_id=subject_id, predicate=predicate, value=value,
                as_of=as_of, source_id=source.id, locator={"path": predicate},
                extracted_by=ExtractedBy.rule)
    db.add(fact)
    db.flush()
    return fact


def _setup(db: Session) -> tuple[Investor, Candidate, Source, Company]:
    investor = Investor(name="Partner")
    company = Company(crustdata_company_id=101, name="Acme", domain="acme.in")
    person = Person(crustdata_person_id=202, name="Asha Rao")
    source = Source(kind=SourceKind.crustdata, endpoint_or_url="/company/enrich",
                    reliability_tier=ReliabilityTier.a)
    db.add_all([investor, company, person, source])
    db.flush()
    db.add(CompanyPerson(company_id=company.id, person_id=person.id, role="founder"))
    search = Search(investor_id=investor.id, query_text="fintech", parsed_filters={},
                    unresolved=[], as_of=date(2026, 11, 1))
    db.add(search)
    db.flush()
    candidate = Candidate(search_id=search.id, company_id=company.id, breakdown=[])
    db.add(candidate)
    company_facts: list[tuple[str, Any, date | None]] = [
        ("industries", ["Fintech"], None), ("hq_country", "India", None),
        ("description", "GST reconciliation", None), ("headcount_total", 26, None),
        ("headcount_at", 20, date(2026, 4, 1)), ("headcount_at", 26, date(2026, 10, 1)),
        ("competitors", ["a.com", "b.com"], None),
        ("news_item", {"title": "Launch"}, date(2026, 10, 20)),
    ]
    for predicate, value, as_of in company_facts:
        _fact(db, source, SubjectType.company, company.id, predicate, value, as_of)
    _fact(db, source, SubjectType.person, person.id, "employment",
          {"title": "Engineer", "company_name": "Bank", "start": "2018-01-01"}, date(2018, 1, 1))
    _fact(db, source, SubjectType.person, person.id, "headline", "Builder")
    db.flush()
    return investor, candidate, source, company


def test_score_candidate_writes_breakdown_signals_snapshot(db: Session) -> None:
    _, candidate, source, company = _setup(db)
    scored = score_candidate(db, candidate.id)
    db.commit()

    assert scored.score is not None and scored.suggested_action is not None
    keys = {c["key"]: c for c in scored.breakdown}
    assert keys["funding"]["score"] == "unknown"
    assert keys["traction"]["fact_ids"] and keys["team"]["fact_ids"]
    assert 0 < float(scored.completeness or 0) < 1
    kinds = {s.kind for s in db.scalars(select(Signal).where(
        Signal.candidate_id == candidate.id))}
    assert SignalKind.gap in kinds and SignalKind.strong in kinds
    snaps = db.scalars(select(ScoreSnapshot)).all()
    assert len(snaps) == 1 and snaps[0].delta == [] and snaps[0].profile_version == 0

    # new evidence → second snapshot with a per-criterion delta; old signals replaced
    _fact(db, source, SubjectType.company, company.id, "last_round_type", "seed")
    signals_before = len(db.scalars(select(Signal)).all())
    score_candidate(db, candidate.id, SnapshotTrigger.watch_event)
    db.commit()
    snaps = db.scalars(select(ScoreSnapshot).order_by(ScoreSnapshot.created_at)).all()
    assert len(snaps) == 2 and snaps[1].trigger == SnapshotTrigger.watch_event
    delta = {d["key"]: d for d in snaps[1].delta}
    assert delta["funding"]["before"] == "unknown" and "funding now known" in (
        snaps[1].reason or "")
    assert len(db.scalars(select(Signal)).all()) == signals_before - 1  # funding gap closed


def test_contradicted_claim_lowers_score(db: Session) -> None:
    _, candidate, _, _ = _setup(db)
    before = float(score_candidate(db, candidate.id).score or 0)
    claim = Claim(candidate_id=candidate.id, quote="team of 60", predicate="headcount",
                  value=60, as_of=date(2026, 10, 1))
    db.add(claim)
    db.flush()
    db.add(Verification(claim_id=claim.id, result=VerificationResult.contradicted, fact_ids=[]))
    db.flush()
    after = score_candidate(db, candidate.id, SnapshotTrigger.dd_ingest)
    assert float(after.score or 0) < before
    assert any("contradicted" in s.text for s in db.scalars(select(Signal)))
    assert len(score_search(db, candidate.search_id)) == 1


def test_get_candidate_shape_and_scope(client: TestClient, db: Session) -> None:
    investor, candidate, _, _ = _setup(db)
    score_candidate(db, candidate.id)
    db.commit()
    headers = {"X-Investor-Id": str(investor.id)}

    response = client.get(f"/candidates/{candidate.id}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["company"]["name"] == "Acme" and body["company"]["headcount"] == 26
    assert body["company"]["one_liner"] == "GST reconciliation"
    assert body["founders"][0]["name"] == "Asha Rao"
    assert body["founders"][0]["headline"] == "Builder"
    traction = next(c for c in body["breakdown"] if c["key"] == "traction")
    assert traction["facts"][0]["citation"]["endpoint_or_url"] == "/company/enrich"
    assert traction["facts"][0]["citation"]["locator"] == {"path": "headcount_at"}
    assert any(c["score"] == "unknown" for c in body["breakdown"])
    assert body["signals"] and body["questions"] == []
    assert len(body["score_history"]) == 1 and body["score_history"][0]["delta"] is None

    other = client.get(f"/candidates/{candidate.id}",
                       headers={"X-Investor-Id": str(uuid.uuid4())})
    assert other.status_code == 404


def test_rescore_route_adds_snapshot(client: TestClient, db: Session) -> None:
    investor, candidate, _, _ = _setup(db)
    db.commit()
    headers = {"X-Investor-Id": str(investor.id)}

    first = client.post(f"/candidates/{candidate.id}/rescore", headers=headers)
    second = client.post(f"/candidates/{candidate.id}/rescore", headers=headers)

    assert first.status_code == 200 and second.status_code == 200
    history = second.json()["score_history"]
    assert [h["trigger"] for h in history] == ["profile_change", "profile_change"]
    assert history[1]["delta"] == {}
    assert client.post(f"/candidates/{candidate.id}/rescore",
                       headers={"X-Investor-Id": str(uuid.uuid4())}).status_code == 404
