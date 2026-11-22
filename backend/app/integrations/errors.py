"""Errors raised by the integration clients."""

from typing import Any


class IntegrationError(Exception):
    """Base class for integration failures."""


class SourceUnavailable(IntegrationError):
    """The source kept failing (5xx, timeouts, or 429s) after all retries."""


class CreditsExhausted(IntegrationError):
    """Crustdata answered 402: no credits left on the account or key."""


class CrustdataAuthError(IntegrationError):
    """Crustdata answered 401/403: bad key or endpoint not enabled."""


class CrustdataBadRequest(IntegrationError):
    """Crustdata rejected the request (400 or another 4xx); `body` holds its error."""

    def __init__(self, status: int, body: Any) -> None:
        super().__init__(f"crustdata {status}: {body}")
        self.status = status
        self.body = body


class LLMError(IntegrationError):
    """The model gave no valid answer after the retry, or refused."""
