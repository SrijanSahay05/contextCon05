from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import RedirectResponse

from app.deps import current_investor_id
from app.errors import AUTH_RESPONSES, ERROR_RESPONSES, not_implemented
from app.schemas.gmail import GmailConnect, GmailStatus

router = APIRouter(prefix="/integrations/gmail", tags=["gmail"], responses=ERROR_RESPONSES)
_auth = [Depends(current_investor_id)]


@router.get("", response_model=GmailStatus, dependencies=_auth,
            responses=AUTH_RESPONSES)
def gmail_status() -> GmailStatus:
    """Whether Gmail is connected, and as which address."""
    not_implemented()


@router.get("/connect", response_model=GmailConnect, dependencies=_auth,
            responses=AUTH_RESPONSES)
def gmail_connect() -> GmailConnect:
    """Returns Google's consent-screen URL (send + read scopes). Navigate the browser to
    `auth_url`; a plain redirect wouldn't work because navigation can't send
    `X-Investor-Id`. The `state` inside the URL identifies the investor on the callback."""
    not_implemented()


@router.get(
    "/callback", response_class=RedirectResponse, status_code=status.HTTP_307_TEMPORARY_REDIRECT
)
def gmail_callback(code: str = Query(...), state: str = Query(...)) -> RedirectResponse:
    """Google redirects here (no `X-Investor-Id`; `state` identifies the investor). Stores
    the token and redirects back to the app's settings page."""
    not_implemented()


@router.delete("", response_model=GmailStatus, dependencies=_auth,
               responses=AUTH_RESPONSES)
def gmail_disconnect() -> GmailStatus:
    """Disconnect Gmail and delete the stored token. Returns `connected: false`."""
    not_implemented()
