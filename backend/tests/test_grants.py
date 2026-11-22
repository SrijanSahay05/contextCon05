from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.llm import FakeLLM
from app.models.entities import Company
from app.models.enums import ExtractedBy
from app.models.evidence import Fact, Source
from app.services.search import grants
from tests.test_discovery import FakeWorld, make_clients, noop

SEED_FUND = "https://seedfund.startupindia.gov.in/awardees/paysetu"
QUOTE = "Paysetu was awarded ₹20 lakh under the Startup India Seed Fund Scheme"
CLAIM = {"program": "Startup India Seed Fund Scheme", "amount": "₹20 lakh",
         "date": "2026-06-01", "quote": QUOTE}


def company(db: Session) -> Company:
    row = Company(crustdata_company_id=700101, name="Paysetu")
    db.add(row)
    db.commit()
    return row


def check(db: Session, fake: FakeWorld, llm: FakeLLM) -> dict[str, Any]:
    row = company(db)
    out = grants.check_grants(db, make_clients(fake, llm), [(row.id, row.name)],
                              date(2025, 5, 22), noop)
    db.commit()
    return out


def test_quoted_grant_becomes_a_fact(db: Session) -> None:
    fake = FakeWorld()
    out = check(db, fake, FakeLLM({"grants": [CLAIM]}, {"grants": []}))
    fact = db.scalars(select(Fact)).one()
    assert fact.predicate == grants.GRANT and fact.extracted_by == ExtractedBy.llm
    assert fact.value == CLAIM and str(fact.as_of) == "2026-06-01"
    assert fact.locator == {"url": SEED_FUND, "quote": QUOTE}
    assert db.get_one(Source, fact.source_id).endpoint_or_url == SEED_FUND
    assert out["verified"][0]["fact_ids"] == [fact.id]

    searches = fake.paths("/web/search/live")
    assert searches[0]["sources"] == ["web"] and "site:birac.nic.in" in searches[0]["query"]
    assert searches[1]["sources"] == ["news"]
    assert all(s["start_date"] == 1747872000 for s in searches)  # 2025-05-22 UTC


def test_quote_not_on_page_is_dropped(db: Session) -> None:
    invented = CLAIM | {"quote": "Paysetu received a ₹1 crore BIRAC BIG grant"}
    out = check(db, FakeWorld(), FakeLLM({"grants": [invented]}, {"grants": []}))
    assert db.scalars(select(Fact)).all() == []
    assert out["verified"] == []
    [miss] = out["unverifiable"]
    assert miss["urls"] == [SEED_FUND, "https://news.example.in/paysetu-grant"]


def test_nothing_found_is_unverifiable_with_what_was_searched(db: Session) -> None:
    fake = FakeWorld()
    fake.world["web_results"] = []
    out = check(db, fake, FakeLLM())
    [miss] = out["unverifiable"]
    assert miss["fact_ids"] == [] and len(miss["searched"]) == 2
    assert fake.paths("/web/enrich/live") == []
