import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.actions import Watch, WatchEvent
from app.models.enums import (
    RunKind,
    SourceKind,
    SuggestedAction,
    WatchEventStatus,
    WatchReason,
)
from app.models.evidence import Source
from app.models.identity import Investor
from app.models.runs import Job, Run
from app.models.search import Candidate, Search
from app.services import clients
from app.services.watch import diff as d
from app.services.watch.watcher import ensure_watch
from tests.test_candidates_routes import _setup
from tests.test_integrations_crustdata import fixture

SECRET = "s3cret"
BASE = "https://scout.example.com"


# --- diff rules -------------------------------------------------------------------

BEFORE: d.Snapshot = {
    "headcount_total": [40], "funding_round": [{"round_type": "seed", "amount_usd": 1e6}],
    "news_item": [{"title": "Launch"}], "industries": [["Fintech"]],
    "description": ["GST reconciliation"],
    "founder": [{"name": "Asha"}, {"name": "Ravi"}],
}


def _after(**changes: Any) -> d.Snapshot:
    return {**json.loads(json.dumps(BEFORE)), **changes}


def test_no_change_is_empty() -> None:
    assert d.diff(BEFORE, _after()) == []
    assert d.diff(BEFORE, _after(headcount_total=[43])) == []  # +7.5% is below 10%
    assert d.suggest([], 90) is None


def test_unfetched_predicate_is_not_a_change() -> None:
    assert d.diff(BEFORE, {"headcount_total": [40]}) == []
    assert d.diff({"headcount_total": [40]}, _after(news_item=[{"title": "x"}])) == []


@pytest.mark.parametrize(("after", "kind", "field"), [
    ({"headcount_total": [60]}, d.HEADCOUNT, "headcount_total"),
    ({"funding_round": [{"round_type": "seed", "amount_usd": 1e6},
                        {"round_type": "series_a", "amount_usd": 8e6}]}, d.NEW_ROUND,
     "funding_round"),
    ({"news_item": [{"title": "Launch"}, {"title": "Raises A"}]}, d.NEWS, "news_item"),
    ({"industries": [["Healthcare"]]}, d.PIVOT, "industries"),
    ({"description": ["Hospital billing"]}, d.PIVOT, "description"),
    ({"founder": [{"name": "Asha"}]}, d.FOUNDER_LEFT, "founder"),
])
def test_each_change_kind(after: d.Snapshot, kind: str, field: str) -> None:
    [change] = d.diff(BEFORE, _after(**after))
    assert (change["kind"], change["field"]) == (kind, field)
    assert set(change) == {"field", "before", "after", "summary", "kind"}


def test_headcount_summary_and_suggestions() -> None:
    [grow] = d.diff(BEFORE, _after(headcount_total=[60]))
    assert grow["summary"] == "Headcount +50% (40 → 60)"
    assert d.suggest([grow], 80) == SuggestedAction.reach_out
    assert d.suggest([grow], 30) == SuggestedAction.request_data
    [drop] = d.diff(BEFORE, _after(headcount_total=[20]))
    assert d.suggest([drop], 80) == SuggestedAction.watch
    assert d.suggest([drop], None) == SuggestedAction.pass_
    small = d.diff(BEFORE, _after(funding_round=[{"round_type": "seed", "amount_usd": 1e6},
                                                 {"round_type": "angel", "amount_usd": 1e5}]))
    assert d.suggest(small, 90) is None  # a small round alone is not worth acting on
    left = d.diff(BEFORE, _after(founder=[{"name": "Asha"}], headcount_total=[60]))
    assert d.suggest(left, 90) == SuggestedAction.watch  # bad news wins


# --- watch creation ---------------------------------------------------------------

def test_ensure_watch_creates_once_with_docs_body(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "webhook_secret", SECRET)
    seen: list[tuple[str, dict[str, Any]]] = []
    created = fixture("crustdata/watch_company_create")["response"]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=created)

    c = clients.clients_for_run(None, transport=httpx.MockTransport(handler))
    _, candidate, _, company = _setup(db)
    first = ensure_watch(db, c, candidate, WatchReason.watch, BASE + "/")
    again = ensure_watch(db, c, candidate, WatchReason.watch, BASE)
    assert again.id == first.id and first.crustdata_watch_id == 46936

    # another investor's candidate for the same company shares the Crustdata watch
    other = Investor(name="Other")
    db.add(other)
    db.flush()
    search = Search(investor_id=other.id, query_text="x", parsed_filters={}, unresolved=[])
    db.add(search)
    db.flush()
    twin = Candidate(search_id=search.id, company_id=company.id, breakdown=[])
    db.add(twin)
    db.flush()
    shared = ensure_watch(db, c, twin, WatchReason.watch, BASE)
    assert shared.id != first.id and shared.crustdata_watch_id == 46936

    [(path, body)] = seen
    assert path == "/watch/company"
    assert body["entities"] == {"crustdata_company_ids": [101]}
    assert body["config"]["trigger"] == {"type": "interval", "every_hours": 720}
    assert body["notifications"] == [{"type": "webhook", "url":
                                      f"{BASE}/webhooks/crustdata/watch?token={SECRET}"}]
    assert body["track"]["op"] == "or" and body["fields"]


# --- webhook ----------------------------------------------------------------------

def _watched(db: Session) -> tuple[Investor, Candidate, Watch]:
    investor, candidate, _, company = _setup(db)
    watch = Watch(company_id=company.id, candidate_id=candidate.id, crustdata_watch_id=46936,
                  reason=WatchReason.pass_)
    db.add(watch)
    db.commit()
    return investor, candidate, watch


@pytest.mark.parametrize("token", ["wrong", ""])
def test_webhook_rejects_bad_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    monkeypatch.setattr(get_settings(), "webhook_secret", SECRET)
    response = client.post(f"/webhooks/crustdata/watch?token={token}", json={})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_allowed"


def test_webhook_rejects_when_no_secret_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "webhook_secret", "")
    assert client.post("/webhooks/crustdata/watch?token=", json={}).status_code == 401


def test_test_notification_enqueues_recheck(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "webhook_secret", SECRET)
    investor, candidate, _ = _watched(db)
    envelope = fixture("crustdata/watch_test_notification")["response"]["envelope"]

    url = f"/webhooks/crustdata/watch?token={SECRET}"
    assert client.post(url, json=envelope).status_code == 204
    [job] = db.scalars(select(Job).where(Job.kind == "recheck")).all()
    source = db.get_one(Source, job.payload["source"])
    assert source.kind == SourceKind.crustdata and source.raw_id
    assert job.payload["candidate_id"] == str(candidate.id)
    assert job.payload["investor_id"] == str(investor.id)
    assert db.get_one(Run, job.run_id).kind == RunKind.recheck

    # an unknown watch is accepted and ignored
    other = {"metadata": {"watch_id": 1}, "results": []}
    assert client.post(url, json=other).status_code == 204
    assert len(db.scalars(select(Job).where(Job.kind == "recheck")).all()) == 1


def test_webhook_matches_by_company_id(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "webhook_secret", SECRET)
    _watched(db)
    body = {"metadata": {"watch_id": 999}, "results": [
        {"changes": [], "record": {"crustdata_company_id": 101}}]}
    assert client.post(f"/webhooks/crustdata/watch?token={SECRET}", json=body).status_code == 204
    assert db.scalar(select(Job).where(Job.kind == "recheck")) is not None


# --- inbox ------------------------------------------------------------------------

def test_events_listing_is_scoped_and_dismiss(client: TestClient, db: Session) -> None:
    investor, candidate, watch = _watched(db)
    change = {"field": "headcount_total", "before": 40, "after": 60, "kind": d.HEADCOUNT,
              "summary": "Headcount +50% (40 → 60)"}
    event = WatchEvent(watch_id=watch.id, changes=[change],
                       suggested_action=SuggestedAction.reach_out)
    db.add(event)
    db.commit()
    mine = {"X-Investor-Id": str(investor.id)}

    body = client.get("/watch-events?status=open", headers=mine).json()
    assert body["total"] == 1
    [item] = body["items"]
    assert item["company_name"] == "Acme" and item["reason"] == "pass"
    assert item["candidate_id"] == str(candidate.id)
    assert item["changes"] == [{k: change[k] for k in ("field", "before", "after", "summary")}]
    assert item["suggested_reason"] == "Headcount +50% (40 → 60)"

    stranger = {"X-Investor-Id": "3f2b8c1e-6a4d-4e2f-9b1a-7c5d2e8f0a11"}
    assert client.get("/watch-events", headers=stranger).json() == {"items": [], "total": 0}
    assert client.post(f"/watch-events/{event.id}/dismiss",
                       headers=stranger).status_code == 404

    dismissed = client.post(f"/watch-events/{event.id}/dismiss", headers=mine)
    assert dismissed.status_code == 200 and dismissed.json()["status"] == "dismissed"
    assert client.get("/watch-events?status=open", headers=mine).json()["total"] == 0
    db.refresh(event)
    assert event.status == WatchEventStatus.dismissed
