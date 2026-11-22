from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, not_implemented
from app.schemas.source import SourceOut

router = APIRouter(
    prefix="/sources", tags=["sources"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)


@router.get("/{source_id}", response_model=SourceOut)
def get_source(source_id: UUID) -> SourceOut:
    """The raw snapshot behind a citation (click-through from any fact or claim)."""
    not_implemented()
