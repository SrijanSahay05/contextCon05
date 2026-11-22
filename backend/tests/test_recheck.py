import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.actions import Watch, WatchEvent
from app.models.enums import RunKind, SnapshotTrigger, WatchReason
from app.models.runs import Job, Run, RunStep
from app.models.search import Candidate, ScoreSnapshot
from app.services import clients
from app.services.jobs import queue
from app.services.jobs.registry import HANDLERS
from app.services.jobs.steps import StepRunner
from app.services.watch import recheck_job
from tests.test_candidates_routes import _setup

ACME = {
    "crustdata_company_id": 101,
    "basic_info": {"name": "Acme", "primary_domain": "acme.in",
                   "description": "GST reconciliation"},
    "taxonomy": {"professional_network_industries": ["Fintech"]},
    "headcount": {"total": 40},
}


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/company/enrich"
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json=[{"matched_on": "101", "matches": [
            {"company_data": ACME}]}])

    monkeypatch.setattr(recheck_job, "clients_for_run", lambda run_id: clients.clients_for_run(
        run_id, transport=httpx.MockTransport(handler)))
    return bodies


def _run(db: Session, candidate: Candidate) -> Run:
    row = queue.create_run(db, RunKind.recheck, {"candidate_id": str(candidate.id)})
    db.commit()
    HANDLERS["recheck"](db, StepRunner(db, row.id), {"candidate_id": str(candidate.id)})
    return row


def test_headcount_jump_makes_event_and_rescore(db: Session, seen: list[dict[str, Any]]) -> None:
    _, candidate, _, company = _setup(db)  # headcount_total 26 on file
    watch = Watch(company_id=company.id, candidate_id=candidate.id, crustdata_watch_id=1,
                  reason=WatchReason.watch)
    db.add(watch)
    db.commit()

    row = _run(db, candidate)

    assert seen == [{"crustdata_company_ids": [101],
                     "fields": ["basic_info", "headcount", "funding", "taxonomy", "locations"]}]
    steps = db.scalars(select(RunStep).where(RunStep.run_id == row.id)
                       .order_by(RunStep.seq)).all()
    assert [s.name for s in steps] == ["snapshot_before", "enrich", "diff", "rescore", "event"]
    [event] = db.scalars(select(WatchEvent)).all()
    [change] = event.changes
    assert (change["kind"], change["before"], change["after"]) == ("headcount_change", 26, 40)
    assert event.watch_id == watch.id and event.suggested_action is not None
    assert str(event.source_id) == steps[1].output["source_id"]
    [snap] = db.scalars(select(ScoreSnapshot)).all()
    assert snap.trigger == SnapshotTrigger.watch_event

    # same data again: nothing moved, so re-scored but no new event
    _run(db, candidate)
    assert len(db.scalars(select(WatchEvent)).all()) == 1
    assert len(db.scalars(select(ScoreSnapshot)).all()) == 2


def test_unwatched_candidate_rescored_without_event(
    db: Session, seen: list[dict[str, Any]]
) -> None:
    _, candidate, _, _ = _setup(db)
    db.commit()
    row = _run(db, candidate)
    event = db.scalar(select(RunStep).where(RunStep.run_id == row.id, RunStep.name == "event"))
    assert event is not None and event.output == {"event_id": None, "changes": 1,
                                                  "watched": False}
    assert db.scalar(select(WatchEvent)) is None


def test_recheck_route_is_idempotent_per_day(client: TestClient, db: Session) -> None:
    investor, candidate, _, _ = _setup(db)
    db.commit()
    headers = {"X-Investor-Id": str(investor.id)}
    first = client.post(f"/candidates/{candidate.id}/recheck", headers=headers)
    again = client.post(f"/candidates/{candidate.id}/recheck", headers=headers)
    assert first.status_code == again.status_code == 202
    assert first.json()["run_id"] == again.json()["run_id"]
    [job] = db.scalars(select(Job).where(Job.kind == "recheck")).all()
    assert job.payload == {"candidate_id": str(candidate.id), "investor_id": str(investor.id)}
    stranger = {"X-Investor-Id": "3f2b8c1e-6a4d-4e2f-9b1a-7c5d2e8f0a11"}
    assert client.post(f"/candidates/{candidate.id}/recheck",
                       headers=stranger).status_code == 404
