import copy
import json
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import Company, CompanyPerson, Person
from app.models.enums import ExtractedBy, SourceKind, SubjectType
from app.models.evidence import Fact, Source
from app.services.evidence import facts_mapper as fm
from app.services.evidence.entities import link_person, upsert_company, upsert_person

FIXTURES = Path(__file__).parent / "fixtures" / "crustdata"
PREFIX = "[0].matches[0]"


def _response(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())["response"]


def _company(name: str = "company_enrich.json") -> dict[str, Any]:
    data: dict[str, Any] = _response(name)[0]["matches"][0]["company_data"]
    return data


def _person() -> dict[str, Any]:
    data: dict[str, Any] = _response("person_enrich.json")[0]["matches"][0]["person_data"]
    return data


_TOKEN = re.compile(r'\.?([A-Za-z_]\w*)|\[(\d+)\]|\["([^"]+)"\]')


def _resolve(root: Any, path: str) -> Any:
    pos = 0
    while pos < len(path):
        m = _TOKEN.match(path, pos)
        assert m, f"bad path {path!r} at {pos}"
        key, index, quoted = m.groups()
        root = root[int(index)] if index is not None else root[key or quoted]
        pos = m.end()
    return root


def _by(drafts: list[fm.FactDraft], predicate: str) -> list[fm.FactDraft]:
    return [d for d in drafts if d.predicate == predicate]


def _one(drafts: list[fm.FactDraft], predicate: str) -> Any:
    [d] = _by(drafts, predicate)
    return d.value


def test_company_basic_and_funding() -> None:
    record = _company()
    drafts = fm.map_company(record)

    assert _one(drafts, fm.NAME) == "Lumen Ledger"
    assert _one(drafts, fm.DOMAIN) == "lumenledger.io"
    assert _one(drafts, fm.YEAR_FOUNDED) == 2019
    assert _one(drafts, fm.DESCRIPTION).startswith("Accounting automation")
    assert _one(drafts, fm.FUNDING_TOTAL_USD) == 198500000
    assert _one(drafts, fm.LAST_ROUND_TYPE) == "private_equity"
    [last] = _by(drafts, fm.LAST_ROUND_DATE)
    assert (last.value, last.as_of) == ("2025-02-18", date(2025, 2, 18))
    assert "Accel-KKR" in _one(drafts, fm.INVESTORS)

    rounds = _by(drafts, fm.FUNDING_ROUND)
    milestones = record["funding"]["milestones"]
    assert len(rounds) == len(milestones)
    assert [r.as_of for r in rounds] == [date.fromisoformat(m["funding_date"]) for m in milestones]
    assert rounds[0].value == {"round_type": "pre_seed", "amount_usd": 1500000,
                               "investors": ["Angel Collective", "Sequoia Surge"],
                               "lead_investors": ["Sequoia Surge"]}
    assert rounds[2].path == "funding.milestones[2]"

    total = _by(drafts, fm.HEADCOUNT_TOTAL)[0]
    assert (total.value, total.as_of) == (412, date(2026, 11, 1))  # latest point: no updated_at
    points = _by(drafts, fm.HEADCOUNT_AT)
    assert len(points) == len(record["headcount"]["timeseries"])
    assert (points[0].value, points[0].as_of) == (301, date(2024, 11, 1))

    # sections the fixture does not have produce nothing
    for missing in (fm.FOUNDER, fm.NEWS_ITEM, fm.HQ_COUNTRY, fm.INDUSTRIES, fm.COMPETITORS,
                    fm.WEB_TRAFFIC_MONTHLY, fm.HEADCOUNT_BY_FUNCTION):
        assert _by(drafts, missing) == []


def test_company_full_record_covers_every_section() -> None:
    drafts = fm.map_company(_company("company_enrich_full.json"))

    assert {d.predicate for d in drafts} == {
        fm.NAME, fm.DOMAIN, fm.DESCRIPTION, fm.INDUSTRIES, fm.HQ_COUNTRY, fm.HQ_CITY,
        fm.YEAR_FOUNDED, fm.HEADCOUNT_TOTAL, fm.HEADCOUNT_AT, fm.HEADCOUNT_BY_FUNCTION,
        fm.FUNDING_TOTAL_USD, fm.LAST_ROUND_TYPE, fm.LAST_ROUND_DATE, fm.FUNDING_ROUND,
        fm.INVESTORS, fm.FOUNDER, fm.NEWS_ITEM, fm.WEB_TRAFFIC_MONTHLY, fm.COMPETITORS,
    }
    assert _one(drafts, fm.INDUSTRIES) == ["Robotics Engineering", "Utilities"]
    assert _one(drafts, fm.HQ_COUNTRY) == "India"
    assert _by(drafts, fm.HEADCOUNT_TOTAL)[0].as_of == date(2026, 11, 15)  # updated_at wins
    assert _one(drafts, fm.HEADCOUNT_BY_FUNCTION)["Engineering"] == 12
    # an unparseable date keeps the fact, with no as_of
    assert [p.as_of for p in _by(drafts, fm.HEADCOUNT_AT)] == [date(2026, 5, 1), None,
                                                               date(2026, 11, 1)]
    assert [f.value for f in _by(drafts, fm.FOUNDER)] == [
        {"name": "Ravi Menon", "crustdata_person_id": 880101, "title": "Co-founder & CEO"},
        {"name": "Meera Iyer", "crustdata_person_id": 880102, "title": "Co-founder & CTO"},
    ]
    [news] = _by(drafts, fm.NEWS_ITEM)
    assert news.value["title"] == "Quillwave raises seed round"
    assert news.as_of == date(2025, 9, 15)
    traffic = {"domain": "quillwave.ai", "monthly_visitors": 4200}
    assert _one(drafts, fm.WEB_TRAFFIC_MONTHLY) == traffic


def test_paths_resolve_into_the_raw_response() -> None:
    for name, kind, mapper in [
        ("company_enrich.json", "company_data", fm.map_company),
        ("company_enrich_full.json", "company_data", fm.map_company),
        ("person_enrich.json", "person_data", fm.map_person),
    ]:
        raw = _response(name)
        drafts = mapper(raw[0]["matches"][0][kind], f"{PREFIX}.{kind}")
        assert drafts
        for d in drafts:
            assert d.path.startswith(f"{PREFIX}.{kind}.")
            target = _resolve(raw, d.path)
            if isinstance(d.value, (str, int, float, list)) and d.predicate not in (
                fm.LAST_ROUND_DATE,
            ):
                assert target == d.value, d
            else:
                assert target is not None, d


def test_person_mapping() -> None:
    record = _person()
    record["skills"] = {"professional_network_skills": ["Fintech", "Product Management"]}
    drafts = fm.map_person(record)

    assert _one(drafts, fm.NAME) == "Ananya Rao"
    assert _one(drafts, fm.HEADLINE) == "Co-founder & CEO @ Lumen Ledger"
    assert _one(drafts, fm.CURRENT_TITLE) == "Co-founder & CEO"
    assert _one(drafts, fm.LOCATION) == "Bengaluru, Karnataka, India"
    assert _one(drafts, fm.SKILLS) == ["Fintech", "Product Management"]
    assert _one(drafts, fm.CURRENT_EMPLOYER) == {"name": "Lumen Ledger",
                                                 "crustdata_company_id": 700001}
    jobs = _by(drafts, fm.EMPLOYMENT)
    assert [j.value for j in jobs] == [
        {"title": "Co-founder & CEO", "company_name": "Lumen Ledger",
         "crustdata_company_id": 700001, "start": "2019-01-01"},
        {"title": "Product Manager", "company_name": "Razorpay",
         "crustdata_company_id": 640123, "start": "2015-07-01", "end": "2018-12-01"},
    ]
    assert [j.as_of for j in jobs] == [date(2019, 1, 1), date(2015, 7, 1)]
    assert _one(drafts, fm.EDUCATION) == {
        "school": "Birla Institute of Technology and Science, Pilani",
        "degree": "Bachelor of Engineering (B.E.)", "field": "Computer Science",
        "start": "2011-08-01", "end": "2015-05-01",
    }


def test_missing_fields_produce_no_facts() -> None:
    assert fm.map_company({}) == []
    assert fm.map_person({"basic_profile": {"name": None, "headline": ""}}) == []
    sparse = copy.deepcopy(_company())
    del sparse["funding"]
    sparse["basic_info"]["description"] = None
    drafts = fm.map_company(sparse)
    assert not {fm.DESCRIPTION, fm.FUNDING_ROUND, fm.INVESTORS} & {d.predicate for d in drafts}
    assert all(d.value is not None for d in drafts)


def _source(db: Session) -> uuid.UUID:
    source = Source(kind=SourceKind.crustdata, endpoint_or_url="/company/enrich")
    db.add(source)
    db.flush()
    return source.id


def test_persist_facts_is_idempotent(db: Session) -> None:
    source_id = _source(db)
    company = upsert_company(db, _company())
    drafts = fm.map_company(_company())

    first = fm.persist_facts(db, SubjectType.company, company.id, drafts, source_id)
    again = fm.persist_facts(db, SubjectType.company, company.id, drafts, source_id)
    db.commit()

    assert [f.id for f in first] == [f.id for f in again]
    assert db.scalar(select(func.count()).select_from(Fact)) == len(drafts)
    stored = first[0]
    assert stored.extracted_by == ExtractedBy.rule
    assert stored.locator == {"path": drafts[0].path}


def test_upsert_is_one_row_per_crustdata_id(db: Session) -> None:
    record = _company()
    first = upsert_company(db, record)
    renamed = copy.deepcopy(record)
    renamed["basic_info"]["name"] = "Lumen Ledger Inc"
    del renamed["basic_info"]["primary_domain"]
    second = upsert_company(db, renamed)
    db.commit()

    assert second.id == first.id
    assert db.scalar(select(func.count()).select_from(Company)) == 1
    assert (second.name, second.domain) == ("Lumen Ledger Inc", "lumenledger.io")

    person = upsert_person(db, _person())
    again = upsert_person(db, _person() | {"basic_profile": {"name": "Ananya R."}})
    assert again.id == person.id and again.name == "Ananya R."
    assert again.linkedin_url == "https://www.linkedin.com/in/ananya-rao-ll"
    assert db.scalar(select(func.count()).select_from(Person)) == 1

    link_person(db, first, person, "founder")
    link_person(db, first, person, "founder")
    db.commit()
    assert db.scalar(select(func.count()).select_from(CompanyPerson)) == 1
