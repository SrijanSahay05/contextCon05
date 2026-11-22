"""The error envelope every non-2xx response uses, and the handlers that produce it.

Shape: ``{"error": {"code": "not_found", "message": "...", "details": {}}}``.
"""

from enum import StrEnum
from typing import Any, NoReturn

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode(StrEnum):
    not_found = "not_found"
    validation_error = "validation_error"
    conflict = "conflict"
    not_allowed = "not_allowed"
    upstream_unavailable = "upstream_unavailable"
    credits_exhausted = "credits_exhausted"
    ceiling_reached = "ceiling_reached"
    not_implemented = "not_implemented"


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"code": "not_found", "message": "Candidate not found", "details": {}}
            ]
        }
    )


class ErrorEnvelope(BaseModel):
    """Every error response has this shape. Branch on `error.code`, not the message."""

    error: ErrorBody

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "error": {
                        "code": "not_allowed",
                        "message": "Cannot move a candidate from 'new' to 'invest'",
                        "details": {"from": "new", "to": "invest"},
                    }
                }
            ]
        }
    )


class ApiError(Exception):
    """Raise anywhere in a request to return the envelope with this status and code."""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def not_implemented() -> NoReturn:
    raise ApiError(501, ErrorCode.not_implemented, "This endpoint is not implemented yet")


_STATUS_CODES = {
    400: ErrorCode.validation_error,
    401: ErrorCode.not_allowed,
    403: ErrorCode.not_allowed,
    404: ErrorCode.not_found,
    405: ErrorCode.not_allowed,
    409: ErrorCode.conflict,
    422: ErrorCode.validation_error,
    501: ErrorCode.not_implemented,
}


def _envelope(status_code: int, code: ErrorCode, message: str, details: Any) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details}}
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


async def _api_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return _envelope(exc.status_code, exc.code, exc.message, exc.details)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    default = (
        ErrorCode.validation_error if exc.status_code < 500 else ErrorCode.upstream_unavailable
    )
    code = _STATUS_CODES.get(exc.status_code, default)
    return _envelope(exc.status_code, code, str(exc.detail), {})


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Drop `input`/`ctx`: they can echo uploaded content and aren't always JSON-safe.
    errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return _envelope(422, ErrorCode.validation_error, "Request validation failed",
                     {"errors": errors})


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)


# Documented on every router so the OpenAPI spec shows the envelope, not FastAPI's default.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "Not found"},
    422: {"model": ErrorEnvelope, "description": "Validation error"},
    501: {"model": ErrorEnvelope, "description": "Not implemented yet"},
}
AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    **ERROR_RESPONSES,
    401: {"model": ErrorEnvelope, "description": "Missing `X-Investor-Id` header"},
}
