"""Stable public API error envelope."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@dataclass(slots=True)
class APIError(Exception):
    status_code: int
    code: str
    message: str
    retryable: bool = False
    context: dict[str, Any] = field(default_factory=dict)
    retry_after: int | None = None
    details: list[dict[str, Any]] = field(default_factory=list)


async def api_error_handler(request: Request, error: APIError) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after is not None else None
    return JSONResponse(
        status_code=error.status_code,
        headers=headers,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "request_id": request_id,
                "retryable": error.retryable,
                "details": error.details,
                "context": error.context,
            }
        },
    )


async def request_validation_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    details = []
    for issue in error.errors():
        path = [part for part in issue["loc"] if part not in {"body", "query", "path", "header"}]
        kind = str(issue["type"])
        code = "invalid_field"
        message = "This field is invalid."
        if kind == "missing":
            code, message = "required", "This field is required."
        elif kind == "extra_forbidden":
            code, message = "unknown_field", "This field is not allowed."
        elif kind == "value_error" and path == ["period"]:
            code, message, path = (
                "invalid_period",
                "End date must not precede start date.",
                ["period", "end_date"],
            )
        details.append({"code": code, "message": message, "path": path})
    details.sort(key=lambda item: str(item["path"]))
    return await api_error_handler(
        request,
        APIError(
            status_code=422,
            code="validation_failed",
            message="The request contains invalid fields.",
            details=details,
        ),
    )
