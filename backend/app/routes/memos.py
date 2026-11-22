from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, not_implemented
from app.schemas.common import RunAccepted
from app.schemas.memo import MemoOut

router = APIRouter(
    tags=["memos"], responses=AUTH_RESPONSES, dependencies=[Depends(current_investor_id)]
)


@router.post(
    "/candidates/{candidate_id}/memo",
    response_model=RunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_memo(candidate_id: UUID) -> RunAccepted:
    """Generate (or regenerate) the investment memo. When the run is `done`,
    `GET /candidates/{id}` has `latest_memo_id`."""
    not_implemented()


@router.get("/memos/{memo_id}", response_model=MemoOut)
def get_memo(memo_id: UUID) -> MemoOut:
    """The memo as markdown with `[n]` citation markers, the citations, and sentences the
    checker removed for lacking support."""
    not_implemented()
