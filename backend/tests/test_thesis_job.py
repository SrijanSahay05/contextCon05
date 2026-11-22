import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ProfileOrigin, ReviewStatus, RunKind
from app.models.identity import Fund, FundAlias, Investor, InvestorPostLink
from app.models.onboarding import Deal, ScoringProfile, Thesis
from app.services import clients
from app.services.jobs import queue
from app.services.jobs.steps import StepRunner
from app.services.onboarding import thesis_job

FIXTURES = Path(__file__).parent / "fixtures" / "crustdata"
ROUTES = {
    "/company/search": "company_search",
    "/company/enrich": "company_enrich",
    "/person/enrich": "person_enrich",
    "/social_post/search": "social_post_search",
}


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    seen: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        fx = json.loads((FIXTURES / f"{ROUTES[request.url.path]}.json").read_text())
        return httpx.Response(200, json=fx["response"], headers=fx["headers"])

    monkeypatch.setattr(
        thesis_job, "clients_for_run",
        lambda run_id: clients.clients_for_run(run_id, transport=httpx.MockTransport(handler)),
    )
    return seen


def seed_fund(db: Session) -> tuple[Investor, Fund]:
    fund = Fund(name="Accel", domain="accel.com")
    db.add(fund)
    db.flush()
    investor = Investor(name="Ananya Rao", linkedin_url="https://www.linkedin.com/in/ananya-rao-ll",
                        fund_id=fund.id)
    db.add(investor)
    db.flush()
    db.add(FundAlias(fund_id=fund.id, permalink="accel", canonical_name="Accel",
                     confirmed_by=investor.id, confirmed_at=datetime.now(UTC)))
    db.commit()
    return investor, fund


def run_job(db: Session, investor: Investor, fund: Fund) -> None:
    run = queue.create_run(db, RunKind.onboarding, {"investor_id": str(investor.id)})
    db.commit()
    thesis_job.onboarding_thesis(db, StepRunner(db, run.id), {
        "investor_id": str(investor.id), "fund_id": str(fund.id), "as_of": "2021-12-01",
    })


def test_job_builds_deals_thesis_and_profile(
    db: Session, requests: list[tuple[str, dict[str, Any]]],
) -> None:
    investor, fund = seed_fund(db)
    run_job(db, investor, fund)

    deals = db.scalars(select(Deal).order_by(Deal.round_date)).all()
    assert [(d.round_type, d.led) for d in deals] == [("seed", True), ("series_a", False)]
    assert all(d.championed_by_investor_id == investor.id for d in deals)
    assert db.scalars(select(InvestorPostLink)).one().investor_id == investor.id

    thesis = db.scalars(select(Thesis)).one()
    assert thesis.status == ReviewStatus.draft and thesis.version == 1
    # two Accel rounds in one company: the seed is the investment, the series A a follow-on
    assert thesis.deal_count == 1 and thesis.confidence == "low"
    assert str(thesis.window_start) == "2018-12-01"  # widened to 36 months
    entries = {str(d.id) for d in deals if d.match_evidence["entry"]}
    assert entries == {i for p in thesis.points for i in p["deal_ids"]}
    [stage] = [p for p in thesis.points if p["dimension"] == "stage"]
    assert stage["value"]["follow_on_rounds"] == 1
    assert thesis.summary

    profile = db.scalars(select(ScoringProfile)).one()
    assert profile.origin == ProfileOrigin.generic and profile.thesis_id == thesis.id

    search = next(body for path, body in requests if path == "/company/search")
    assert search["filters"]["conditions"][0] == {
        "field": "funding.investors", "type": "in", "value": ["Accel"]}
    enrich = next(body for path, body in requests if path == "/company/enrich")
    assert enrich["crustdata_company_ids"] == [700001, 662397]


def test_rerun_does_not_duplicate_deals(
    db: Session, requests: list[tuple[str, dict[str, Any]]],
) -> None:
    investor, fund = seed_fund(db)
    run_job(db, investor, fund)
    run_job(db, investor, fund)
    assert len(db.scalars(select(Deal)).all()) == 2
    assert [t.version for t in db.scalars(select(Thesis).order_by(Thesis.version))] == [1, 2]


def test_unknown_investor_without_linkedin_skips_partner(
    db: Session, requests: list[tuple[str, dict[str, Any]]],
) -> None:
    investor, fund = seed_fund(db)
    investor.linkedin_url = None
    db.commit()
    run_job(db, investor, fund)
    assert not any(path == "/person/enrich" for path, _ in requests)
    assert db.scalars(select(Thesis)).one().fund_id == fund.id
