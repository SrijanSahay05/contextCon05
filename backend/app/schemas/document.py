from uuid import UUID

from pydantic import BaseModel

from app.models.enums import DDItemKind, DocumentOrigin, ParseStatus
from app.schemas.common import EX_CANDIDATE_ID, EX_DOCUMENT_ID, EX_RUN_ID, examples


class DocumentOut(BaseModel):
    """An uploaded document. Parsing runs in the background: follow `run_id`, then
    re-fetch the DD view for the extracted claims."""

    id: UUID
    candidate_id: UUID
    kind: DDItemKind
    origin: DocumentOrigin
    filename: str | None
    mime: str
    sha256: str
    parse_status: ParseStatus
    page_count: int | None
    run_id: UUID | None

    model_config = examples({
        "id": EX_DOCUMENT_ID,
        "candidate_id": EX_CANDIDATE_ID,
        "kind": "deck",
        "origin": "vc_upload",
        "filename": "Ledgerline_Seed_Deck_Nov2026.pdf",
        "mime": "application/pdf",
        "sha256": "9f2c6b1e4a7d8c3f0b5e2a9d6c1f4b7e8a3d0c5f2b9e6a1d4c7f0b3e8a5d2c9f",
        "parse_status": "pending",
        "page_count": None,
        "run_id": EX_RUN_ID,
    })
