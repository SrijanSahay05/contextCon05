from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, not_implemented
from app.models.enums import WatchEventStatus
from app.schemas.watch import WatchEventList, WatchEventOut

router = APIRouter(
    prefix="/watch-events", tags=["watch"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)


@router.get("", response_model=WatchEventList)
def list_watch_events(
    status: WatchEventStatus | None = Query(None, description="e.g. `open` for the inbox"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> WatchEventList:
    """Changes at watched and passed companies, newest first, with a suggested action."""
    not_implemented()


@router.post("/{event_id}/dismiss", response_model=WatchEventOut)
def dismiss_watch_event(event_id: UUID) -> WatchEventOut:
    """Dismiss an event (`open → dismissed`). Acting on it (e.g. a status change) marks it
    `acted` automatically."""
    not_implemented()
