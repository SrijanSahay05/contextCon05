"""Job kind → handler. Later phases register their handlers here."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.services.jobs.steps import StepRunner

Handler = Callable[[Session, StepRunner, dict[str, Any]], None]

HANDLERS: dict[str, Handler] = {}


def register(kind: str) -> Callable[[Handler], Handler]:
    def decorator(handler: Handler) -> Handler:
        HANDLERS[kind] = handler
        return handler

    return decorator
