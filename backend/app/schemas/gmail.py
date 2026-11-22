from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import examples


class GmailStatus(BaseModel):
    """Whether the partner's Gmail is connected. Uploads work without it."""

    connected: bool
    email: str | None
    status: Literal["active", "revoked", "error"] | None
    scopes: list[str]
    connected_at: datetime | None

    model_config = examples(
        {
            "connected": True,
            "email": "ananya@kestrel.vc",
            "status": "active",
            "scopes": ["https://www.googleapis.com/auth/gmail.send",
                       "https://www.googleapis.com/auth/gmail.readonly"],
            "connected_at": "2026-11-20T09:40:00Z",
        },
        {"connected": False, "email": None, "status": None, "scopes": [], "connected_at": None},
    )
