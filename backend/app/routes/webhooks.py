from typing import Any

from fastapi import APIRouter, Body, Query, status

from app.errors import ERROR_RESPONSES, not_implemented

router = APIRouter(prefix="/webhooks", tags=["webhooks"], responses=ERROR_RESPONSES)


@router.post("/crustdata/watch", status_code=status.HTTP_204_NO_CONTENT)
def crustdata_watch(
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
    not_implemented()
