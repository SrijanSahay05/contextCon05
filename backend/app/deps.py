from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import APIKeyHeader

from app.errors import ApiError, ErrorCode

# shortcut: the investor id stands in for auth; replace with real sessions before any
# multi-user deployment.
_investor_header = APIKeyHeader(
    name="X-Investor-Id",
    auto_error=False,
    description="The current investor's id (uuid), from `POST /investors/onboard`.",
)


def current_investor_id(
    raw: Annotated[str | None, Depends(_investor_header)],
) -> UUID:
    """Reads `X-Investor-Id`: missing → 401 `not_allowed`, not a uuid → 422."""
    if not raw:
        raise ApiError(401, ErrorCode.not_allowed, "X-Investor-Id header is required")
    try:
        return UUID(raw)
    except ValueError:
        raise ApiError(
            422, ErrorCode.validation_error, "X-Investor-Id must be a uuid", {"value": raw}
        ) from None


InvestorId = Annotated[UUID, Depends(current_investor_id)]
