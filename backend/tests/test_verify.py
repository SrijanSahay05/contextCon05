import uuid
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dd import Claim, DDItem, DDRequest, Document, Verification
from app.models.entities import Company, CompanyPerson, Person
from app.models.enums import (
    CandidateStatus,
    DDItemKind,
    DDItemStatus,
    DDStage,
    DocumentOrigin,
    ExtractedBy,
    ReliabilityTier,
    RunKind,
    SnapshotTrigger,
    SourceKind,
    SubjectType,
)
from app.models.enums import VerificationResult as R
from app.models.evidence import Fact, Source
from app.models.identity import Investor
from app.models.search import Candidate, ScoreSnapshot, Search
from app.services.dd.verify import verify
from app.services.dd.verify_job import verify_claims
from app.services.jobs import queue
from app.services.jobs.steps import StepRunner
from app.services.scoring.rules import Item
from app.services.scoring.service import score_candidate

FACTS = [
    Item(1, "headcount_at", 18, date(2026, 10, 1), tier="A"),
    Item(2, "headcount_at", 12, date(2026, 4, 1), tier="A"),
    Item(3, "funding_round", {"round_type": "seed", "amount_usd": 2_000_000},
         date(2025, 6, 10), tier="A"),
    Item(4, "education", {"school": "IIT Bombay", "degree": "B.Tech"}, None, "p1", tier="A"),
    Item(5, "employment", {"company_name": "Razorpay", "title": "Engineer"}, None, "p1",
         tier="A"),
]


def claim(predicate: str, value: Any, as_of: date | None = None) -> Item:
    return Item("c", predicate, value, as_of)


@pytest.mark.parametrize(("item", "expected", "fact_ids"), [
    (claim("headcount_total", 20, date(2026, 10, 15)), R.verified, [1]),
    (claim("headcount_total", 18, None), R.verified, [1]),  # undated → latest fact
    (claim("headcount_total", 30, date(2025, 1, 1)), R.unverifiable, []),  # > 60 days apart
    (claim("funding_round", {"round_type": "Seed", "amount_usd": 2_100_000},
           date(2025, 6, 1)), R.verified, [3]),
    (claim("funding_round", {"round_type": "seed", "amount_usd": 5_000_000},
           date(2025, 6, 1)), R.contradicted, [3]),
    (claim("funding_round", {"round_type": "series_a"}), R.unverifiable, []),
    (claim("education", {"school": "iit bombay"}), R.verified, [4]),
    (claim("education", "Stanford"), R.contradicted, [4]),
    (claim("employment", {"company_name": "razorpay", "title": "engineer"}), R.verified, [5]),
    (claim("grant", {"program": "BIRAC BIG"}), R.unverifiable, []),
    (claim("revenue_usd", 1_000_000), R.self_reported, []),
    (claim("market_size_usd", 1e9), R.unverifiable, []),
])
def test_verify_table(item: Item, expected: R, fact_ids: list[int]) -> None:
    result, ids, _ = verify(item, FACTS)
    assert (result, ids) == (expected, fact_ids)


def test_contradicted_headcount_note_shows_both_values() -> None:
    result, ids, note = verify(claim("headcount_total", 40, date(2026, 10, 20)), FACTS)
    assert result == R.contradicted and ids == [1]
    assert "40" in note and "18" in note and "2026-10-01" in note


def test_grant_verified_by_web_fact() -> None:
    facts = [Item(9, "grant", {"program": "BIRAC BIG Grant", "quote": "..."}, None, tier="B")]
    assert verify(claim("grant", "birac big"), facts)[0] == R.verified


# --- the verify_claims job end to end --------------------------------------------------

def _fact(db: Session, source: Source, subject: SubjectType, subject_id: uuid.UUID,
          predicate: str, value: Any, as_of: date | None = None) -> Fact:
    fact = Fact(subject_type=subject, subject_id=subject_id, predicate=predicate, value=value,
                as_of=as_of, source_id=source.id, locator={"path": predicate},
                extracted_by=ExtractedBy.rule)
    db.add(fact)
    db.flush()
    return fact


def test_verify_claims_job(db: Session) -> None:
    investor = Investor(name="Partner")
    company = Company(crustdata_company_id=301, name="Ledgerline", domain="ledgerline.in")
    person = Person(crustdata_person_id=401, name="Rohan")
    source = Source(kind=SourceKind.crustdata, endpoint_or_url="/company/enrich",
                    reliability_tier=ReliabilityTier.a)
    db.add_all([investor, company, person, source])
    db.flush()
    db.add(CompanyPerson(company_id=company.id, person_id=person.id, role="founder"))
    search = Search(investor_id=investor.id, query_text="fintech", parsed_filters={},
                    unresolved=[], as_of=date(2026, 11, 1))
    db.add(search)
    db.flush()
    candidate = Candidate(search_id=search.id, company_id=company.id, breakdown=[],
                          status=CandidateStatus.in_dd, dd_stage=DDStage.awaiting_founder)
    db.add(candidate)
    db.flush()
    hc = _fact(db, source, SubjectType.company, company.id, "headcount_at", 18,
               date(2026, 10, 1))
    _fact(db, source, SubjectType.company, company.id, "headcount_at", 12, date(2026, 4, 1))
    _fact(db, source, SubjectType.company, company.id, "industries", ["Fintech"])
    _fact(db, source, SubjectType.person, person.id, "education",
          {"school": "IIT Delhi"})
    score_candidate(db, candidate.id)  # the "before" snapshot

    request = DDRequest(candidate_id=candidate.id, round=1)
    db.add(request)
    db.flush()
    deck_item = DDItem(dd_request_id=request.id, kind=DDItemKind.deck)
    fin_item = DDItem(dd_request_id=request.id, kind=DDItemKind.financials)
    grant_item = DDItem(dd_request_id=request.id, kind=DDItemKind.grant_letter)
    document = Document(candidate_id=candidate.id, kind=DDItemKind.deck,
                        origin=DocumentOrigin.vc_upload, storage_path="x.pdf",
                        mime="application/pdf", sha256="a" * 64)
    db.add_all([deck_item, fin_item, grant_item, document])
    db.flush()
    claims = {p: Claim(candidate_id=candidate.id, document_id=document.id, page=4, quote=q,
                       predicate=p, value=v, as_of=d)
              for p, v, d, q in [
                  ("headcount_total", 40, date(2026, 10, 15), "40 engineers"),
                  ("education", {"school": "IIT Delhi"}, None, "IIT Delhi alum"),
                  ("revenue_usd", 500_000, None, "$500k revenue"),
              ]}
    db.add_all(claims.values())
    db.commit()

    run = queue.create_run(db, RunKind.dd, {"candidate_id": str(candidate.id)})
    payload = {"candidate_id": str(candidate.id), "document_id": str(document.id)}
    verify_claims(db, StepRunner(db, run.id), payload)

    results = {c.predicate: v for c, v in (
        (c, db.scalar(select(Verification).where(Verification.claim_id == c.id)))
        for c in claims.values())}
    headcount = results["headcount_total"]
    assert headcount is not None and headcount.result == R.contradicted
    assert headcount.fact_ids == [hc.id] and headcount.tolerance_used == {"pct": 0.15,
                                                                          "days": 60}
    assert results["education"] is not None and results["education"].result == R.verified
    assert results["revenue_usd"] is not None
    assert results["revenue_usd"].result == R.self_reported

    db.expire_all()
    assert deck_item.status == DDItemStatus.contradicted and deck_item.document_id == document.id
    assert fin_item.status == DDItemStatus.received  # revenue: self-reported only
    assert grant_item.status == DDItemStatus.requested

    snaps = db.scalars(select(ScoreSnapshot).order_by(ScoreSnapshot.created_at)).all()
    assert [s.trigger for s in snaps] == [SnapshotTrigger.initial, SnapshotTrigger.dd_ingest]
    traction = next(d for d in snaps[1].delta if d["key"] == "traction")
    assert isinstance(traction["change"], float) and traction["change"] < 0
    assert candidate.dd_stage == DDStage.ready_for_decision

    # re-running (a fresh run) verifies nothing twice
    rerun = queue.create_run(db, RunKind.dd, {"candidate_id": str(candidate.id)})
    verify_claims(db, StepRunner(db, rerun.id), payload)
    assert len(db.scalars(select(Verification)).all()) == 3


def test_round_type_labels_and_exact_company_fields_from_live_run() -> None:
    from app.services.dd.verify import verify as check
    from app.services.scoring.rules import Item

    facts = [Item(1, "last_round_type", "series_c", None, "company"),
             Item(2, "year_founded", 2019, None, "company")]
    assert check(Item("a", "last_round_type", "Series C", None, "company"),
                 facts)[0] == "verified"
    assert check(Item("b", "year_founded", 2019, None, "company"),
                 facts)[0] == "verified"
    assert check(Item("c", "year_founded", 2017, None, "company"),
                 facts)[0] == "contradicted"


def test_grant_claim_named_like_ingestion_matches_the_web_fact() -> None:
    from app.services.dd.verify import verify as check
    from app.services.scoring.rules import Item

    facts = [Item(1, "grant", {"program": "iDEX - DIO", "quote": "..."}, None, "company")]
    claim = Item("g", "grant", {"name": "iDEX", "amount": None}, None, "company")
    assert check(claim, facts)[0] == "verified"


def test_grant_claim_matches_a_crustdata_grant_round() -> None:
    from app.services.dd.verify import verify as check
    from app.services.scoring.rules import Item

    facts = [Item(1, "funding_round", {"round_type": "grant", "investors": ["iDEX - DIO"]},
                  None, "company")]
    claim = Item("g", "grant", {"name": "iDEX"}, None, "company")
    assert check(claim, facts)[0] == "verified"
