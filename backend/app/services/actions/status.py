"""Candidate status moves (`POST /candidates/{id}/status`), recording overrides."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.errors import ApiError, ErrorCode
from app.integrations.errors import CrustdataAuthError, CrustdataBadRequest, SourceUnavailable
from app.models.actions import Watch, WatchEvent
from app.models.enums import CandidateStatus
from app.models.enums import CandidateStatus as S
from app.models.enums import SnapshotTrigger, SuggestedAction, WatchEventStatus, WatchReason
from app.models.search import Candidate
from app.repositories import scores
from app.schemas.candidate import StatusChange
from app.services.clients import clients_for_run
from app.services.scoring.service import score_candidate
from app.services.watch.watcher import ensure_watch

logger = logging.getLogger(__name__)

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


def _after_move(db: Session, candidate: Candidate) -> None:
    """Watch/pass start tracking the company; any move settles its open watch events."""
    db.execute(update(WatchEvent)
               .where(WatchEvent.watch_id.in_(
                   select(Watch.id).where(Watch.candidate_id == candidate.id)))
               .where(WatchEvent.status == WatchEventStatus.open)
               .values(status=WatchEventStatus.acted))
    if candidate.status not in (CandidateStatus.watch, CandidateStatus.pass_):
        return
    reason = WatchReason.watch if candidate.status == CandidateStatus.watch else WatchReason.pass_
    try:
        ensure_watch(db, clients_for_run(None), candidate, reason,
                     get_settings().public_base_url)
    except (SourceUnavailable, CrustdataAuthError, CrustdataBadRequest):
        # the status change stands; tracking falls back to a local watch (manual recheck)
        logger.exception("Crustdata watch creation failed for candidate %s", candidate.id)
        ensure_watch(db, clients_for_run(None), candidate, reason, "")


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
    _after_move(db, candidate)
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
