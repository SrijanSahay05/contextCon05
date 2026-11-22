import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.mongo import mongo_db
from app.models.entities import Company, CompanyPerson, Person
from app.models.enums import SubjectType
from app.models.evidence import Fact, Source
from app.repositories.candidates import company_facts, founder_facts
from app.schemas.search import FilterSpec
from app.services import clients
from app.services.evidence.sources import _raw_response
from app.services.search import discovery
from tests.test_facts_mapper import _resolve

WORLD = json.loads((Path(__file__).parent / "fixtures" / "search" / "discovery.json").read_text())

SCHOOL = {"field": "education.school", "op": "in", "value": ["BITS Pilani"],
          "display": "Founder studied at BITS"}
INDUSTRY = {"field": "industries", "op": "in", "value": ["Financial Services"],
            "display": "Fintech"}
SEMANTIC = {"field": "description", "op": "semantic", "value": "payments infrastructure",
            "display": "Payments infra"}


class FakeWorld:
    """Serves the fixture world by endpoint; enrich and jobs answer per requested id/url."""

    def __init__(self) -> None:
        self.world: dict[str, Any] = json.loads(json.dumps(WORLD))
        self.seen: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, body = request.url.path, json.loads(request.content)
        self.seen.append((path, body))
        w = self.world
        data: Any
        if path == "/person/search":
            founders = "company_id" in json.dumps(body["filters"])
            data = w["founders"] if founders else w["people_route"]
        elif path == "/company/search":
            data = w["company_route"]
        elif path == "/company/enrich":
            data = [{"matched_on": str(i), "matches": (
                [{"company_data": w["companies"][str(i)]}] if str(i) in w["companies"] else [])}
                for i in body["crustdata_company_ids"]]
        elif path == "/person/enrich":
            data = [{"matched_on": u, "matches": [{"person_data": w["people"][u]}]}
                    for u in body["professional_network_profile_urls"] if u in w["people"]]
        elif path == "/job/search":
            data = {"job_listings": w["jobs"].get(str(body["filters"]["value"]), [])}
        elif path == "/web/search/live":
            data = {"success": True, "results": w["web_results"]}
        elif path == "/web/enrich/live":
            url = body["urls"][0]
            data = [{"success": url in w["pages"], "url": url, "content": w["pages"].get(url)}]
        else:
            return httpx.Response(400, json={"error": path})
        return httpx.Response(200, json=data, headers={"x-credits-used": "1"})

    def paths(self, path: str) -> list[dict[str, Any]]:
        return [body for p, body in self.seen if p == path]


def make_clients(fake: FakeWorld, llm: httpx.BaseTransport | None = None) -> clients.Clients:
    return clients.clients_for_run(None, transport=httpx.MockTransport(fake), llm_transport=llm)


def spec(**kw: Any) -> FilterSpec:
    return FilterSpec.model_validate(kw)


def noop() -> None:
    pass


def discover(fake: FakeWorld, **kw: Any) -> dict[str, Any]:
    return discovery.discover(make_clients(fake), spec(**kw), date(2026, 11, 22), noop)


def test_people_route_adds_founder_titles_and_returns_employers() -> None:
    fake = FakeWorld()
    out = discover(fake, people=[SCHOOL])
    assert out["mode"] == "people"
    assert [c["crustdata_company_id"] for c in out["candidates"]] == [700101, 700102]
    [body] = fake.paths("/person/search")
    school, titles = body["filters"]["conditions"]
    assert school == {"field": "education.schools.school", "type": "in", "value": ["BITS Pilani"]}
    assert titles["op"] == "or"
    assert {c["value"] for c in titles["conditions"]} == {"founder", "co-founder", "cofounder"}
    assert {c["field"] for c in titles["conditions"]} == {discovery.TITLE_FIELD}


def test_company_route_uses_semantic_mode_and_industry_filter() -> None:
    fake = FakeWorld()
    out = discover(fake, companies=[INDUSTRY, SEMANTIC], funding=[
        {"field": "last_funding_round_type", "op": "in", "value": ["seed"], "display": "Seed"}],
        window_months=18)
    assert [c["crustdata_company_id"] for c in out["candidates"]] == [700103, 700101]
    [body] = fake.paths("/company/search")
    assert body["search"] == {"query": "payments infrastructure", "mode": "semantic"}
    assert body["filters"]["conditions"] == [
        {"field": "basic_info.industries", "type": "in", "value": ["Financial Services"]},
        {"field": "funding.last_round_type", "type": "in", "value": ["seed"]},
        {"field": "funding.last_fundraise_date", "type": "=>", "value": "2025-05-22"},
    ]


def test_both_routes_intersect_when_they_overlap() -> None:
    out = discover(FakeWorld(), people=[SCHOOL], companies=[INDUSTRY])
    assert out["mode"] == "intersection"
    assert out["candidates"] == [
        {"crustdata_company_id": 700101, "found_by": ["people", "company"]}]


def test_both_routes_fall_back_to_flagged_union() -> None:
    fake = FakeWorld()
    fake.world["company_route"]["companies"] = [
        {"crustdata_company_id": 700103, "basic_info": {"name": "GridDeep"}}]
    out = discover(fake, people=[SCHOOL], companies=[INDUSTRY])
    assert out["mode"] == "union"
    assert out["candidates"] == [
        {"crustdata_company_id": 700101, "found_by": ["people"]},
        {"crustdata_company_id": 700102, "found_by": ["people"]},
        {"crustdata_company_id": 700103, "found_by": ["company"]},
    ]


def test_dedupe_and_cap() -> None:
    fake = FakeWorld()
    fake.world["company_route"]["companies"] = [
        {"crustdata_company_id": i % 40} for i in range(80)]
    out = discover(fake, companies=[INDUSTRY])
    ids = [c["crustdata_company_id"] for c in out["candidates"]]
    assert ids == list(range(discovery.MAX_CANDIDATES))
    assert out["route_counts"] == {"company": 40}


def enrich(db: Session, fake: FakeWorld) -> dict[str, Any]:
    out = discovery.enrich(db, make_clients(fake), [700101, 700102, 999999], noop)
    db.commit()
    return out


def _resolves(db: Session, fact: Fact) -> Any:
    source = db.get_one(Source, fact.source_id)
    return _resolve(_raw_response(mongo_db, source.raw_id), fact.locator["path"])


def test_enrich_persists_company_founder_and_role_facts(db: Session) -> None:
    fake = FakeWorld()
    out = enrich(db, fake)
    assert out["missing"] == [999999]
    assert out["founders_found"] == 2 and out["founder_links"] == 2
    paysetu = db.scalars(select(Company).where(Company.crustdata_company_id == 700101)).one()
    assert out["companies"]["700101"] == str(paysetu.id)

    facts = company_facts(db, paysetu.id)
    assert {"name", "headcount_at", "funding_round", "industries", "open_roles"} <= {
        f.predicate for f in facts}
    for f in facts:
        if f.predicate != discovery.OPEN_ROLES:
            assert _resolves(db, f) is not None
    roles = company_facts(db, paysetu.id, [discovery.OPEN_ROLES])
    assert {(r.value["title"], r.value["function"], str(r.as_of)) for r in roles} == {
        ("Backend Engineer", "Engineering", "2026-11-02"), ("Sales Lead", "Sales", "2026-10-20")}
    assert _resolves(db, roles[0])["job_details"]["title"] == roles[0].value["title"]

    links = db.scalars(select(CompanyPerson)).all()
    assert {(link.company_id, link.role) for link in links} == {(paysetu.id, "founder")}
    education = founder_facts(db, paysetu.id, ["education"])
    assert [f.value["school"] for f in education] == ["BITS Pilani"]
    assert _resolves(db, education[0])["school"] == "BITS Pilani"
    assert all(f.subject_type == SubjectType.person for f in founder_facts(db, paysetu.id))

    [search] = fake.paths("/person/search")
    assert search["filters"]["conditions"][0] == {
        "field": "experience.employment_details.current.company_id", "type": "in",
        "value": [700101, 700102]}
    [enrich_body] = fake.paths("/company/enrich")
    assert enrich_body == {"crustdata_company_ids": [700101, 700102, 999999],
                           "fields": discovery.ENRICH_FIELDS}


def test_enrich_rerun_does_not_duplicate(db: Session) -> None:
    enrich(db, FakeWorld())
    counts = (db.scalar(select(func.count()).select_from(Fact)),
              db.scalar(select(func.count()).select_from(Person)))
    enrich(db, FakeWorld())
    assert (db.scalar(select(func.count()).select_from(Fact)),
            db.scalar(select(func.count()).select_from(Person))) == counts
