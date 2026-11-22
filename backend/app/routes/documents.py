from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, not_implemented
from app.models.enums import DDItemKind
from app.schemas.document import DocumentOut

router = APIRouter(
    tags=["documents"], responses=AUTH_RESPONSES, dependencies=[Depends(current_investor_id)]
)


@router.post(
    "/candidates/{candidate_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    candidate_id: UUID,
    file: Annotated[UploadFile, File(description="PDF, XLSX or CSV, max 25 MB")],
    kind: Annotated[DDItemKind, Form()],
) -> DocumentOut:
    """Upload a document for a candidate (`multipart/form-data` with `file` and `kind`).
    Parsing and claim extraction run in the background (`run_id`). Uploading the same
    file twice returns the existing document."""
    not_implemented()
