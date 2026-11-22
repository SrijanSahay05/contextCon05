import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.errors import ERROR_RESPONSES, ApiError, ErrorCode
from app.models.search import Candidate, Search
from app.services.watch.recheck_job import start_recheck
from app.services.watch.watcher import record_delivery, watches_for_delivery

router = APIRouter(prefix="/webhooks", tags=["webhooks"], responses=ERROR_RESPONSES)


@router.post("/crustdata/watch", status_code=status.HTTP_204_NO_CONTENT)
def crustdata_watch(
    db: Annotated[Session, Depends(get_db)],
    token: str = Query(
        description="The shared WEBHOOK_SECRET, embedded in the webhook URL given to "
        "Crustdata when the watch is created. A wrong or missing token returns 401."
    ),
    payload: dict[str, Any] = Body(
        examples=[{"watch_id": "cw_example_123", "event": "headcount_change"}]
    ),
) -> None:
    """Called by Crustdata, not the frontend. Checked with the shared secret in `token`;
    records a watch event and re-scores in the background."""
    secret = get_settings().webhook_secret
    if not secret or not hmac.compare_digest(token.encode(), secret.encode()):
        raise ApiError(401, ErrorCode.not_allowed, "Invalid webhook token")
    source_id = record_delivery(payload)
    for watch in watches_for_delivery(db, payload):
        candidate = db.get_one(Candidate, watch.candidate_id)
        search = db.get_one(Search, candidate.search_id)
        start_recheck(db, candidate, search.investor_id, f"recheck:{candidate.id}:{source_id}",
                      source_id)
