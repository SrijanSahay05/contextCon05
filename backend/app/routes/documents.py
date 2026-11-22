from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import InvestorId, current_investor_id
from app.errors import AUTH_RESPONSES, ErrorEnvelope
from app.models.enums import DDItemKind
from app.repositories.scores import get_owned
from app.schemas.document import DocumentOut
from app.services.dd import ingest

router = APIRouter(
    tags=["documents"], responses=AUTH_RESPONSES, dependencies=[Depends(current_investor_id)]
)


@router.post(
    "/candidates/{candidate_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    responses={413: {"model": ErrorEnvelope, "description": "File is over the size cap"}},
)
def upload_document(
    candidate_id: UUID,
    file: Annotated[UploadFile, File(description="PDF, XLSX or CSV, max 25 MB")],
    kind: Annotated[DDItemKind, Form()],
    investor_id: InvestorId,
    db: Annotated[Session, Depends(get_db)],
) -> DocumentOut:
    """Upload a document for a candidate (`multipart/form-data` with `file` and `kind`).
    Parsing and claim extraction run in the background (`run_id`). Uploading the same
    file twice returns the existing document."""
    return ingest.upload(db, get_owned(db, candidate_id, investor_id), file, kind)
