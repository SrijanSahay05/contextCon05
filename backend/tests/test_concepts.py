import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.llm import FakeLLM
from app.models.entities import Company
from app.models.enums import ExtractedBy, SourceKind, SubjectType
from app.models.evidence import Fact, Source
from app.services.clients import clients_for_run
from app.services.search.concepts import CONCEPT_MATCH, gate

PIXXEL = "Pixxel builds hyperspectral imaging satellites for earth observation."


def company(db: Session, name: str, description: str | None) -> uuid.UUID:
    row = Company(crustdata_company_id=abs(hash(name)) % 10**9, name=name)
    source = Source(kind=SourceKind.crustdata, endpoint_or_url="/company/enrich")
    db.add_all([row, source])
    db.flush()
    if description:
        db.add(Fact(subject_type=SubjectType.company, subject_id=row.id, predicate="description",
                    value=description, as_of=None, source_id=source.id,
                    locator={"path": "[0].matches[0].company_data.basic_info.description"},
                    extracted_by=ExtractedBy.rule))
    db.commit()
    return row.id


def run(db: Session, llm: FakeLLM, ids: list[uuid.UUID]) -> dict[str, object]:
    clients = clients_for_run(None, transport=httpx.MockTransport(lambda r: httpx.Response(500)),
                              llm_transport=llm)
    out = gate(db, clients, ids, ["deeptech"], lambda: None)
    db.commit()
    return out


def test_keeps_only_companies_whose_description_shows_the_concept(db: Session) -> None:
    pixxel = company(db, "Pixxel", PIXXEL)
    lender = company(db, "M2P Fintech", "M2P powers lending and card issuing for banks.")
    llm = FakeLLM(
        {"matches": True, "quote": "hyperspectral imaging satellites", "reason": "space hardware"},
        {"matches": False, "quote": "", "reason": "financial infrastructure software"},
    )
    out = run(db, llm, [pixxel, lender])

    assert out["kept"] == [str(pixxel)]
    assert out["excluded"] == [{"company_id": str(lender), "name": "M2P Fintech",
                                "reason": "financial infrastructure software"}]
    [fact] = db.scalars(select(Fact).where(Fact.predicate == CONCEPT_MATCH)).all()
    assert fact.subject_id == pixxel and fact.value["quote"] == "hyperspectral imaging satellites"
    assert fact.locator["quote"] == "hyperspectral imaging satellites"  # cites the description
    assert llm.requests[0]["model"] == "anthropic/claude-haiku-5.5"


def test_a_quote_not_in_the_description_is_rejected(db: Session) -> None:
    acme = company(db, "Acme", "Acme sells cosmetics online.")
    llm = FakeLLM({"matches": True, "quote": "quantum computing chips", "reason": "deeptech"})
    out = run(db, llm, [acme])
    assert out["kept"] == []
    assert "not supported" in out["excluded"][0]["reason"]  # type: ignore[index]


def test_no_description_is_excluded_without_calling_the_llm(db: Session) -> None:
    blank = company(db, "Blank", None)
    llm = FakeLLM()
    out = run(db, llm, [blank])
    assert out["kept"] == [] and llm.requests == []
