import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.mongo import mongo_db
from app.db.session import SessionLocal
from app.models.enums import Provider, SourceKind, SubjectType, UnitType
from app.services.evidence import facts_mapper as fm
from app.services.evidence.entities import upsert_company
from app.services.evidence.recorder import DbRecorder
from app.services.evidence.sources import fact_out

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "crustdata" / "company_enrich.json").read_text()
)
HEADERS = {"X-Investor-Id": str(uuid.uuid4())}


def _record() -> uuid.UUID:
    return DbRecorder(SessionLocal, mongo_db).record(
        provider=Provider.crustdata, endpoint=FIXTURE["endpoint"], request=FIXTURE["request"],
        response=FIXTURE["response"], units=2.0, unit_type=UnitType.credits, cached=False,
        run_id=None, kind=SourceKind.crustdata, request_hash="h-sources",
    )


def test_source_returns_citation_and_raw(client: TestClient) -> None:
    source_id = _record()

    response = client.get(f"/sources/{source_id}", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["raw"] == FIXTURE["response"]
    citation = body["citation"]
    assert citation["source_id"] == str(source_id)
    assert citation["kind"] == "crustdata"
    assert citation["endpoint_or_url"] == "/company/enrich"
    assert citation["reliability_tier"] == "A"
    assert citation["locator"] == {} and citation["quote"] is None


def test_fact_id_fills_locator(client: TestClient, db: Session) -> None:
    source_id = _record()
    record = FIXTURE["response"][0]["matches"][0]["company_data"]
    company = upsert_company(db, record)
    drafts = fm.map_company(record, "[0].matches[0].company_data")
    facts = fm.persist_facts(db, SubjectType.company, company.id, drafts, source_id)
    db.commit()
    fact = next(f for f in facts if f.predicate == fm.FUNDING_ROUND)

    response = client.get(f"/sources/{source_id}", params={"fact_id": fact.id}, headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["citation"]["locator"] == {
        "path": "[0].matches[0].company_data.funding.milestones[0]"
    }
    out = fact_out(db, fact)
    assert out.citation.source_id == source_id and out.as_of == fact.as_of

    other = client.get(f"/sources/{_record_other()}", params={"fact_id": fact.id},
                       headers=HEADERS)
    assert other.status_code == 404


def _record_other() -> uuid.UUID:
    return DbRecorder(SessionLocal, mongo_db).record(
        provider=Provider.crustdata, endpoint="/person/enrich", request={}, response=[],
        units=1.0, unit_type=UnitType.credits, cached=False, run_id=None,
        kind=SourceKind.crustdata, request_hash="h-other",
    )


def test_unknown_source_is_404_envelope(client: TestClient) -> None:
    response = client.get(f"/sources/{uuid.uuid4()}", headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
