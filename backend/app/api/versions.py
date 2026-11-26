"""Public saved-version history and lifecycle routes."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response

from app.api.dependencies import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    get_version_services,
)
from app.api.errors import APIError
from app.api.report_schemas import ErrorEnvelope
from app.api.version_schemas import (
    CreateVersionRequest,
    RestoredDraftEnvelope,
    RestoreVersionRequest,
    VersionEnvelope,
    VersionListEnvelope,
)
from app.db.repositories import ConcurrencyConflict, IdempotencyConflict
from app.domain.reports import InvalidCursor, ReportNotFound
from app.domain.version_service import VersionNotFound, VersionServices

router = APIRouter(prefix="/api/v1/reports/{report_id}/versions", tags=["versions"])
errors: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorEnvelope} for code in (400, 401, 404, 409, 422)
}


def _not_found() -> APIError:
    return APIError(404, "resource_not_found", "The requested resource was not found.")


def _conflict() -> APIError:
    return APIError(409, "revision_conflict", "The report draft revision has changed.")


def _replay(response: Response, replayed: bool) -> None:
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"


@router.post("", status_code=201, response_model=VersionEnvelope, responses=errors)
async def create_version(
    report_id: UUID,
    command: CreateVersionRequest,
    response: Response,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[VersionServices, Depends(get_version_services)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> VersionEnvelope:
    try:
        detail, replayed = await services.create(
            principal.id, report_id, command.expected_draft_revision, idempotency_key
        )
        _replay(response, replayed)
        return VersionEnvelope(data=detail)
    except ReportNotFound:
        raise _not_found() from None
    except ValueError:
        raise APIError(400, "invalid_request", "The idempotency key is invalid.") from None
    except IdempotencyConflict:
        raise APIError(
            409, "idempotency_conflict", "The idempotency key was used for another command."
        ) from None
    except ConcurrencyConflict:
        raise _conflict() from None


@router.get("", response_model=VersionListEnvelope, responses=errors)
async def list_versions(
    report_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[VersionServices, Depends(get_version_services)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
) -> VersionListEnvelope:
    try:
        data, page = await services.list(principal.id, report_id, limit, cursor)
        return VersionListEnvelope(data=data, page=page)
    except InvalidCursor:
        raise APIError(400, "invalid_cursor", "The cursor is invalid.") from None
    except ReportNotFound:
        raise _not_found() from None


@router.get("/{version_id}", response_model=VersionEnvelope, responses=errors)
async def get_version(
    report_id: UUID,
    version_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[VersionServices, Depends(get_version_services)],
) -> VersionEnvelope:
    try:
        return VersionEnvelope(data=await services.detail(principal.id, report_id, version_id))
    except (ReportNotFound, VersionNotFound):
        raise _not_found() from None


@router.post("/{version_id}/restore", response_model=RestoredDraftEnvelope, responses=errors)
async def restore_version(
    report_id: UUID,
    version_id: UUID,
    command: RestoreVersionRequest,
    response: Response,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[VersionServices, Depends(get_version_services)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> RestoredDraftEnvelope:
    try:
        detail, replayed = await services.restore(
            principal.id,
            report_id,
            version_id,
            command.expected_draft_id,
            command.expected_draft_revision,
            idempotency_key,
        )
        _replay(response, replayed)
        return RestoredDraftEnvelope(data=detail)
    except (ReportNotFound, VersionNotFound):
        raise _not_found() from None
    except ValueError:
        raise APIError(400, "invalid_request", "The idempotency key is invalid.") from None
    except IdempotencyConflict:
        raise APIError(
            409, "idempotency_conflict", "The idempotency key was used for another command."
        ) from None
    except ConcurrencyConflict:
        raise _conflict() from None
