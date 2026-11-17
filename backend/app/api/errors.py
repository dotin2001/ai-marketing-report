"""Stable public API error envelope."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass(slots=True)
class APIError(Exception):
    status_code: int
    code: str
    message: str
    retryable: bool = False
    context: dict[str, Any] = field(default_factory=dict)
    retry_after: int | None = None


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
                "details": [],
                "context": error.context,
            }
        },
    )
