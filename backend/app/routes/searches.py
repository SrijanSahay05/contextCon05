from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, ErrorEnvelope, not_implemented
from app.schemas.common import RunAccepted
from app.schemas.search import FilterSpec, SearchCreate, SearchList, SearchOut

router = APIRouter(
    prefix="/searches", tags=["searches"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)


@router.post("", response_model=SearchOut, status_code=status.HTTP_201_CREATED)
def create_search(body: SearchCreate) -> SearchOut:
    """Parse a plain-language query into filters (status `draft`). Show `parsed_filters`
    as chips and `unresolved` terms with their suggestions. Nothing is searched until
    `POST /searches/{id}/run`."""
    not_implemented()


@router.get("", response_model=SearchList)
def list_searches(
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
) -> SearchList:
    """The investor's searches, newest first (without candidates)."""
    not_implemented()


@router.get("/{search_id}", response_model=SearchOut)
def get_search(search_id: UUID) -> SearchOut:
    """The search and its candidates, highest score first."""
    not_implemented()


@router.put(
    "/{search_id}/filters",
    response_model=SearchOut,
    responses={409: {"model": ErrorEnvelope, "description": "Search is no longer a draft"}},
)
def edit_filters(search_id: UUID, body: FilterSpec) -> SearchOut:
    """Replace the filters after the partner edits the chips. Only while `draft`
    (409 `conflict` otherwise)."""
    not_implemented()


@router.post(
    "/{search_id}/run", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED
)
def run_search(search_id: UUID) -> RunAccepted:
    """Confirm the filters and run the search: find, collect facts, score. When the run is
    `done`, `GET /searches/{id}` has the ranked candidates."""
    not_implemented()
