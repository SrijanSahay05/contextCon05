from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.mongo import mongo_db
from app.db.session import get_db
from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES
from app.schemas.source import SourceOut
from app.services.evidence.sources import source_out

router = APIRouter(
    prefix="/sources", tags=["sources"], responses=AUTH_RESPONSES,
    dependencies=[Depends(current_investor_id)],
)


@router.get("/{source_id}", response_model=SourceOut)
def get_source(
    source_id: UUID,
    fact_id: int | None = Query(
        None, description="A fact citing this source; fills `citation.locator` and `quote`."
    ),
    db: Session = Depends(get_db),
) -> SourceOut:
    """The raw snapshot behind a citation (click-through from any fact or claim)."""
    return source_out(db, mongo_db, source_id, fact_id)
