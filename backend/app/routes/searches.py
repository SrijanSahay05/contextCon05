from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import InvestorId, current_investor_id
from app.errors import AUTH_RESPONSES, ErrorEnvelope
from app.repositories import searches as repo
from app.schemas.common import RunAccepted
from app.schemas.search import FilterSpec, SearchCreate, SearchList, SearchOut
from app.services.search import searches

router = APIRouter(
    prefix="/searches", tags=["searches"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)
Db = Annotated[Session, Depends(get_db)]


@router.post("", response_model=SearchOut, status_code=status.HTTP_201_CREATED)
def create_search(body: SearchCreate, investor_id: InvestorId, db: Db) -> SearchOut:
    """Parse a plain-language query into filters (status `draft`). Show `parsed_filters`
    as chips and `unresolved` terms with their suggestions. Nothing is searched until
    `POST /searches/{id}/run`."""
    return repo.to_out(db, searches.create(db, investor_id, body))


@router.get("", response_model=SearchList)
def list_searches(
    investor_id: InvestorId, db: Db,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
) -> SearchList:
    """The investor's searches, newest first (without candidates)."""
    rows, total = repo.list_owned(db, investor_id, limit, offset)
    return SearchList(items=[repo.to_out(db, s) for s in rows], total=total)


@router.get("/{search_id}", response_model=SearchOut)
def get_search(search_id: UUID, investor_id: InvestorId, db: Db) -> SearchOut:
    """The search and its candidates, highest score first."""
    return repo.to_out(db, repo.get_owned(db, search_id, investor_id), with_candidates=True)


@router.put(
    "/{search_id}/filters",
    response_model=SearchOut,
    responses={409: {"model": ErrorEnvelope, "description": "Search is no longer a draft"}},
)
def edit_filters(
    search_id: UUID, body: FilterSpec, investor_id: InvestorId, db: Db
) -> SearchOut:
    """Replace the filters after the partner edits the chips. Only while `draft`
    (409 `conflict` otherwise)."""
    return repo.to_out(db, searches.edit_filters(db, search_id, investor_id, body))


@router.post(
    "/{search_id}/run", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED
)
def run_search(search_id: UUID, investor_id: InvestorId, db: Db) -> RunAccepted:
    """Confirm the filters and run the search: find, collect facts, score. When the run is
    `done`, `GET /searches/{id}` has the ranked candidates."""
    return searches.run(db, search_id, investor_id)
