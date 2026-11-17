"""Provider-neutral request dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Request

from app.api.errors import APIError
from app.domain.assets import AssetServices


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    id: UUID


async def get_authenticated_principal() -> AuthenticatedPrincipal:
    raise APIError(
        status_code=401,
        code="unauthenticated",
        message="Authentication is required.",
    )


def get_asset_services(request: Request) -> AssetServices:
    service: AssetServices = request.app.state.asset_services
    return service
