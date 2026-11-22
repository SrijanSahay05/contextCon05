import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import CandidateStatus as S
from app.models.enums import SnapshotTrigger
from app.models.search import Candidate, ScoreSnapshot
from app.services.actions.status import FOLLOWS
from app.services.scoring.service import score_candidate
from tests.test_candidates_routes import _setup

ALLOWED = {
    ("new", "shortlist"), ("new", "watch"), ("new", "pass"),
    ("shortlist", "watch"), ("shortlist", "pass"),
    ("in_dd", "invest"), ("in_dd", "watch"), ("in_dd", "pass"),
    ("watch", "shortlist"), ("watch", "pass"),
    ("pass", "watch"),
}


def test_transition_table(client: TestClient, db: Session) -> None:
    investor, candidate, _, _ = _setup(db)
    db.commit()
    headers = {"X-Investor-Id": str(investor.id)}
    for old in S:
        for new in S:
            candidate.status = old
            db.commit()
            response = client.post(f"/candidates/{candidate.id}/status",
                                   json={"status": new}, headers=headers)
            if (old.value, new.value) in ALLOWED:
                assert response.status_code == 200, (old, new)
                assert response.json()["status"] == new.value
                assert response.json()["override"] is None  # no suggestion yet
            else:
                assert response.status_code == 409, (old, new)
                assert response.json()["error"]["code"] == "not_allowed"
                assert response.json()["error"]["details"] == {"from": old, "to": new}
            db.expire_all()

    other = client.post(f"/candidates/{candidate.id}/status", json={"status": "watch"},
                        headers={"X-Investor-Id": str(uuid.uuid4())})
    assert other.status_code == 404


def test_override_recorded_and_rescored(client: TestClient, db: Session) -> None:
    investor, candidate, _, _ = _setup(db)
    suggested = score_candidate(db, candidate.id).suggested_action
    db.commit()
    assert suggested is not None
    target = next(s for s in (S.shortlist, S.watch, S.pass_) if FOLLOWS[suggested] != s)

    response = client.post(f"/candidates/{candidate.id}/status",
                           json={"status": target, "reason": "Met the founder"},
                           headers={"X-Investor-Id": str(investor.id)})

    assert response.status_code == 200
    override = response.json()["override"]
    assert override["action"] == target.value and override["reason"] == "Met the founder"
    assert override["by_investor_id"] == str(investor.id)
    db.expire_all()
    stored = db.get(Candidate, candidate.id)
    assert stored is not None and stored.override is not None
    assert stored.override["from_suggestion"] == suggested.value
    triggers = [s.trigger for s in db.scalars(
        select(ScoreSnapshot).order_by(ScoreSnapshot.created_at))]
    assert triggers == [SnapshotTrigger.initial, SnapshotTrigger.override]


def test_following_the_suggestion_is_not_an_override(client: TestClient, db: Session) -> None:
    investor, candidate, _, _ = _setup(db)
    suggested = score_candidate(db, candidate.id).suggested_action
    db.commit()
    assert suggested is not None
    target = FOLLOWS[suggested]
    if target not in (S.shortlist, S.watch, S.pass_):
        return  # unreachable from `new` for this fixture's suggestion

    response = client.post(f"/candidates/{candidate.id}/status", json={"status": target},
                           headers={"X-Investor-Id": str(investor.id)})

    assert response.status_code == 200 and response.json()["override"] is None
    assert len(response.json()["score_history"]) == 1
