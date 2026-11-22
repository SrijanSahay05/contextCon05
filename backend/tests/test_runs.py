import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import Provider, RunKind, RunStatus, UnitType
from app.models.evidence import Ledger
from app.services.jobs import queue
from app.services.jobs.steps import StepRunner

HEADERS = {"X-Investor-Id": str(uuid.uuid4())}


def _finished_run(db: Session) -> uuid.UUID:
    run = queue.create_run(db, RunKind.search, {"search_id": "s1"})
    db.commit()
    runner = StepRunner(db, run.id)
    runner.step("discover", lambda: {"found": 3})
    db.add(Ledger(run_id=run.id, provider=Provider.crustdata, endpoint="/company/search",
                  units=0.09, unit_type=UnitType.credits))
    run.status = RunStatus.done
    db.commit()
    return run.id


def test_get_run_returns_steps_and_ledger(client: TestClient, db: Session) -> None:
    run_id = _finished_run(db)
    body = client.get(f"/runs/{run_id}", headers=HEADERS).json()
    assert body["status"] == "done"
    assert [s["name"] for s in body["steps"]] == ["discover"]
    assert body["steps"][0]["output"] == {"found": 3}
    assert body["credits_spent"] == 0.09
    assert body["ledger"][0]["endpoint"] == "/company/search"


def test_unknown_run_is_a_404_envelope(client: TestClient) -> None:
    for path in (f"/runs/{uuid.uuid4()}", f"/runs/{uuid.uuid4()}/events"):
        response = client.get(path, headers=HEADERS)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_events_stream_steps_then_end(client: TestClient, db: Session) -> None:
    run_id = _finished_run(db)
    with client.stream("GET", f"/runs/{run_id}/events", headers=HEADERS) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    assert 'event: step\ndata: {"name":"discover","status":"done","seq":0}' in text
    assert "event: run" in text
    assert text.rstrip().endswith("event: end\ndata: {}")
