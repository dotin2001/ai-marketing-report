"""Operational liveness and readiness routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.core.health import ProbeProvider, check_readiness

router = APIRouter(prefix="/health", tags=["health"])


class LiveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


class ReadyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    dependencies: dict[str, Literal["ready", "unavailable"]]


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
async def ready(request: Request) -> ReadyResponse | JSONResponse:
    provider: ProbeProvider = request.app.state.probe_provider
    timeout_seconds: float = request.app.state.health_check_timeout_seconds
    dependencies = await check_readiness(provider, timeout_seconds)
    is_ready = all(value == "ready" for value in dependencies.values())
    response = ReadyResponse(
        status="ready" if is_ready else "not_ready",
        dependencies=dependencies,
    )
    if is_ready:
        return response
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(),
    )
