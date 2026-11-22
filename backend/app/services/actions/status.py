"""Candidate status moves (`POST /candidates/{id}/status`), recording overrides."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.errors import ApiError, ErrorCode
from app.models.enums import CandidateStatus as S
from app.models.enums import SnapshotTrigger, SuggestedAction
from app.models.search import Candidate
from app.repositories import scores
from app.schemas.candidate import StatusChange
from app.services.scoring.service import score_candidate

# `in_dd` is entered only through `POST /candidates/{id}/dd`
ALLOWED: dict[S, set[S]] = {
    S.new: {S.shortlist, S.watch, S.pass_},
    S.shortlist: {S.watch, S.pass_},
    S.in_dd: {S.invest, S.watch, S.pass_},
    S.watch: {S.shortlist, S.pass_},
    S.pass_: {S.watch},
    S.invest: set(),
}
# the status that follows each suggestion; moving anywhere else is an override
FOLLOWS: dict[SuggestedAction, S] = {
    SuggestedAction.reach_out: S.shortlist,
    SuggestedAction.request_data: S.shortlist,
    SuggestedAction.watch: S.watch,
    SuggestedAction.pass_: S.pass_,
    SuggestedAction.invest: S.invest,
}


def change_status(db: Session, investor_id: uuid.UUID, candidate_id: uuid.UUID,
                  body: StatusChange) -> Candidate:
    """Flushes; the caller commits."""
    candidate = scores.get_owned(db, candidate_id, investor_id)
    old = candidate.status
    if body.status not in ALLOWED[old]:
        raise ApiError(409, ErrorCode.not_allowed,
                       f"Cannot move a candidate from '{old}' to '{body.status}'",
                       {"from": str(old), "to": str(body.status)})
    candidate.status = body.status
    candidate.updated_at = func.clock_timestamp()
    suggestion = candidate.suggested_action
    if suggestion is None or FOLLOWS[suggestion] == body.status:
        candidate.override = None
        db.flush()
        db.refresh(candidate)
        return candidate
    candidate.override = {
        "by_investor_id": str(investor_id), "action": str(body.status), "reason": body.reason,
        "at": datetime.now(UTC).isoformat(), "from_suggestion": str(suggestion),
    }
    db.flush()
    return score_candidate(db, candidate.id, SnapshotTrigger.override)
