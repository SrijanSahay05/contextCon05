from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import InvestorId, current_investor_id
from app.errors import AUTH_RESPONSES, ApiError, ErrorCode
from app.models.enums import WatchEventStatus
from app.repositories import watch as repo
from app.schemas.watch import WatchEventList, WatchEventOut
from app.services.watch.watcher import event_out

router = APIRouter(
    prefix="/watch-events", tags=["watch"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=WatchEventList)
def list_watch_events(
    investor_id: InvestorId,
    db: Db,
    status: WatchEventStatus | None = Query(None, description="e.g. `open` for the inbox"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> WatchEventList:
    """Changes at watched and passed companies, newest first, with a suggested action."""
    rows, total = repo.list_events(db, investor_id, status, limit, offset)
    return WatchEventList(items=[event_out(*row) for row in rows], total=total)


@router.post("/{event_id}/dismiss", response_model=WatchEventOut)
def dismiss_watch_event(event_id: UUID, investor_id: InvestorId, db: Db) -> WatchEventOut:
    """Dismiss an event (`open → dismissed`). Acting on it (e.g. a status change) marks it
    `acted` automatically."""
    event, watch, company = repo.get_owned_event(db, event_id, investor_id)
    if event.status == WatchEventStatus.acted:
        raise ApiError(409, ErrorCode.not_allowed, "This event was already acted on",
                       {"from": event.status, "to": WatchEventStatus.dismissed})
    event.status = WatchEventStatus.dismissed
    db.commit()
    return event_out(event, watch, company)
