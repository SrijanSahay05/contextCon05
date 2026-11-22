from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import InvestorId, current_investor_id
from app.errors import AUTH_RESPONSES
from app.schemas.common import RunAccepted
from app.schemas.memo import MemoOut
from app.services.actions import memo

router = APIRouter(
    tags=["memos"], responses=AUTH_RESPONSES, dependencies=[Depends(current_investor_id)]
)
Db = Annotated[Session, Depends(get_db)]


@router.post(
    "/candidates/{candidate_id}/memo",
    response_model=RunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_memo(candidate_id: UUID, investor_id: InvestorId, db: Db) -> RunAccepted:
    """Generate (or regenerate) the investment memo. When the run is `done`,
    `GET /candidates/{id}` has `latest_memo_id`."""
    return memo.request(db, candidate_id, investor_id)


@router.get("/memos/{memo_id}", response_model=MemoOut)
def get_memo(memo_id: UUID, investor_id: InvestorId, db: Db) -> MemoOut:
    """The memo as markdown with `[n]` citation markers, the citations, and sentences the
    checker removed for lacking support."""
    return memo.get(db, memo_id, investor_id)
