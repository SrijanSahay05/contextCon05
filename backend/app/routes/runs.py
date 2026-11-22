from collections.abc import Iterator
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES
from app.schemas.run import RunOut
from app.services import runs as service

router = APIRouter(
    prefix="/runs", tags=["runs"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: UUID, db: Session = Depends(get_db)) -> RunOut:
    """Status, steps, credits spent, hold reason and the last 50 ledger rows. Poll this
    if SSE isn't available; stop when `status` is `done`, `failed` or `held`."""
    return service.get_run(db, run_id)


@router.get(
    "/{run_id}/events",
    response_class=StreamingResponse,
    responses={200: {
        "description": "Server-sent events",
        "content": {"text/event-stream": {"example": (
            'event: step\ndata: {"name": "collect_facts", "status": "done", "seq": 2}\n\n'
            'event: run\ndata: {"status": "done", "credits_spent": 41.25}\n\n'
            "event: end\ndata: {}\n\n"
        )}},
    }},
)
def run_events(run_id: UUID) -> StreamingResponse:
    """Live progress as Server-Sent Events. Events:

    - `step`: `{name, status, seq}` when a step changes (`StepEvent`)
    - `run`: `{status, credits_spent}` when the run changes (`RunEvent`)
    - `end`: `{}` once the run is `done`, `failed` or `held`; then close and
      `GET /runs/{id}` for the final state.

    `EventSource` can't send headers, so use a fetch-based SSE reader with
    `X-Investor-Id`.
    """
    events = service.stream_events(run_id)
    first = next(events)  # raises the 404 envelope before the stream starts
    return StreamingResponse(
        _prepend(first, events), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _prepend(first: str, rest: Iterator[str]) -> Iterator[str]:
    yield first
    yield from rest
