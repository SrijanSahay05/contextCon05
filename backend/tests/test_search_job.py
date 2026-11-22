from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.llm import FakeLLM
from app.models.enums import CandidateStatus, RunKind, SearchStatus, StepStatus
from app.models.evidence import Fact
from app.models.identity import Investor
from app.models.runs import Run, RunStep
from app.models.search import Candidate, Search
from app.repositories.candidates import candidates_for_search
from app.services import clients
from app.services.jobs import queue
from app.services.jobs.registry import HANDLERS
from app.services.jobs.steps import CeilingReached, StepRunner
from app.services.search import search_job
from tests.test_discovery import INDUSTRY, SCHOOL, FakeWorld
from tests.test_grants import CLAIM


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeWorld:
    world = FakeWorld()
    replies: list[dict[str, Any]] = [{"grants": [CLAIM]}, {"grants": []}] * 4
    llm = FakeLLM(*replies)
    monkeypatch.setattr(search_job, "clients_for_run", lambda run_id: clients.clients_for_run(
        run_id, transport=httpx.MockTransport(world), llm_transport=llm))
    return world


def seed(db: Session, **filters: Any) -> Search:
    investor = Investor(name="Ananya Rao")
    db.add(investor)
    db.flush()
    search = Search(investor_id=investor.id, query_text="fintech with a BITS founder",
                    parsed_filters=filters, unresolved=[])
    db.add(search)
    db.commit()
    return search


def run(db: Session, search: Search, ceiling: float | None = None) -> Run:
    row = queue.create_run(db, RunKind.search, {"search_id": str(search.id)})
    if ceiling is not None:
        row.credit_ceiling = ceiling
    db.commit()
    HANDLERS["search_run"](db, StepRunner(db, row.id), {
        "search_id": str(search.id), "investor_id": str(search.investor_id)})
    return row


def test_handler_creates_candidates_with_grants(db: Session, fake: FakeWorld) -> None:
    search = seed(db, people=[SCHOOL], companies=[INDUSTRY], grants={"required": True},
                  window_months=18)
    row = run(db, search)
    [candidate] = candidates_for_search(db, search.id)
    assert candidate.status == CandidateStatus.new
    steps = {s.name: s for s in db.scalars(select(RunStep).where(RunStep.run_id == row.id))}
    assert [s.name for s in sorted(steps.values(), key=lambda s: s.seq)] == [
        "discover", "enrich", "grants", "candidates", "score"]
    assert steps["score"].output == {"scored": 1}
    assert candidate.score is not None and candidate.suggested_action is not None
    db.refresh(search)
    assert search.status == SearchStatus.done
    assert steps["discover"].output["candidates"][0]["found_by"] == ["people", "company"]
    assert steps["candidates"].output == {"candidate_ids": [str(candidate.id)], "count": 1}
    assert len(steps["grants"].output["verified"]) == 1
    assert db.scalar(select(func.count()).select_from(Fact).where(Fact.predicate == "grant")) == 1
    assert db.get_one(Search, search.id).status == search.status  # left to the integrator


def test_rerun_does_not_duplicate(db: Session, fake: FakeWorld) -> None:
    search = seed(db, people=[SCHOOL], grants={"required": True})
    run(db, search)
    facts = db.scalar(select(func.count()).select_from(Fact))
    run(db, search)
    assert len(candidates_for_search(db, search.id)) == 2
    assert db.scalar(select(func.count()).select_from(Candidate)) == 2
    assert db.scalar(select(func.count()).select_from(Fact)) == facts


def test_credit_ceiling_holds_the_run(db: Session, fake: FakeWorld) -> None:
    search = seed(db, people=[SCHOOL], companies=[INDUSTRY])
    with pytest.raises(CeilingReached):
        run(db, search, ceiling=0.5)
    step = db.scalars(select(RunStep)).one()
    assert step.name == "discover" and step.status == StepStatus.failed
    assert len(fake.seen) == 1  # stopped before the second paid call
    assert db.scalars(select(Candidate)).all() == []


def test_fit_runs_before_enrich_and_only_the_cap_is_enriched(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = FakeWorld()
    llm = FakeLLM({"ratings": [
        {"index": 0, "fit": 1, "quote": "battery management chips", "reason": "loose"},
        {"index": 1, "fit": 3, "quote": "UPI payments infrastructure", "reason": "core"},
    ]})
    monkeypatch.setattr(search_job, "clients_for_run", lambda run_id: clients.clients_for_run(
        run_id, transport=httpx.MockTransport(world), llm_transport=llm))
    monkeypatch.setattr(get_settings(), "search_enrich_cap", 1)
    search = seed(db, companies=[INDUSTRY], ranking_query="UPI payments for small merchants")
    row = run(db, search)

    steps = {s.name: s for s in db.scalars(select(RunStep).where(RunStep.run_id == row.id))}
    assert [s.name for s in sorted(steps.values(), key=lambda s: s.seq)] == [
        "discover", "fit", "enrich", "grants", "candidates", "score"]
    # GridDeep was found first, but Paysetu fits better, so only Paysetu is paid for
    [enrich_body] = world.paths("/company/enrich")
    assert enrich_body["crustdata_company_ids"] == [700101]
    assert steps["enrich"].output["fit_facts"] == 1
    [candidate] = candidates_for_search(db, search.id)
    [fact] = db.scalars(select(Fact).where(Fact.predicate == "concept_match")).all()
    assert fact.subject_id == candidate.company_id
    assert fact.value["quote"] == "UPI payments infrastructure"
