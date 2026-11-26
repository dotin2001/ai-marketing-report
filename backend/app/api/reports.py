"""Authenticated report management endpoints."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response

from app.api.dependencies import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    get_report_services,
)
from app.api.errors import APIError
from app.api.report_schemas import (
    CreateReportRequest,
    DraftEnvelope,
    ErrorEnvelope,
    MetadataPatchRequest,
    ReportEnvelope,
    ReportListEnvelope,
    UpdateDraftRequest,
)
from app.db.repositories import ConcurrencyConflict, IdempotencyConflict
from app.domain.reports import DraftValidationError, InvalidCursor, ReportNotFound, ReportServices

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
errors: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorEnvelope} for code in (400, 401, 404, 409, 422)
}
create_responses = {
    **errors,
    201: {
        "model": ReportEnvelope,
        "headers": {
            "Idempotency-Replayed": {
                "description": "Present with value true when the original creation is replayed.",
                "schema": {"type": "string", "enum": ["true"]},
            }
        },
    },
}


def _not_found() -> APIError:
    return APIError(
        404,
        "resource_not_found",
        "The requested report was not found.",
        context={"resource_type": "report"},
    )


def _revision_conflict() -> APIError:
    return APIError(409, "revision_conflict", "The report draft revision has changed.")


@router.post("", status_code=201, response_model=ReportEnvelope, responses=create_responses)
async def create_report(
    command: CreateReportRequest,
    response: Response,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[ReportServices, Depends(get_report_services)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> ReportEnvelope:
    try:
        report, replayed = await services.create(principal.id, command, idempotency_key)
    except ValueError:
        raise APIError(400, "invalid_request", "The idempotency key is invalid.") from None
    except IdempotencyConflict:
        raise APIError(
            409,
            "idempotency_conflict",
            "The idempotency key was used for another command.",
            context={"operation": "create-report"},
        ) from None
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return ReportEnvelope(data=report)


@router.get("", response_model=ReportListEnvelope, responses=errors)
async def list_reports(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[ReportServices, Depends(get_report_services)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
) -> ReportListEnvelope:
    try:
        reports, page = await services.list(principal.id, limit, cursor)
    except InvalidCursor:
        raise APIError(400, "invalid_cursor", "The cursor is invalid.") from None
    return ReportListEnvelope(data=reports, page=page)


@router.get("/{report_id}", response_model=ReportEnvelope, responses=errors)
async def get_report(
    report_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[ReportServices, Depends(get_report_services)],
) -> ReportEnvelope:
    try:
        return ReportEnvelope(data=await services.detail(principal.id, report_id))
    except ReportNotFound:
        raise _not_found() from None


@router.patch("/{report_id}", response_model=ReportEnvelope, responses=errors)
async def patch_report(
    report_id: UUID,
    command: MetadataPatchRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[ReportServices, Depends(get_report_services)],
) -> ReportEnvelope:
    try:
        return ReportEnvelope(data=await services.update_metadata(principal.id, report_id, command))
    except ReportNotFound:
        raise _not_found() from None
    except ConcurrencyConflict:
        raise _revision_conflict() from None


@router.patch("/{report_id}/draft", response_model=DraftEnvelope, responses=errors)
async def patch_draft(
    report_id: UUID,
    command: UpdateDraftRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[ReportServices, Depends(get_report_services)],
) -> DraftEnvelope:
    try:
        return DraftEnvelope(data=await services.update_draft(principal.id, report_id, command))
    except ReportNotFound:
        raise _not_found() from None
    except ConcurrencyConflict:
        raise _revision_conflict() from None
    except DraftValidationError as error:
        raise APIError(
            422,
            "validation_failed",
            "The request contains invalid fields.",
            details=[
                {
                    "code": "invalid_reference",
                    "message": "This reference is invalid.",
                    "path": error.path,
                }
            ],
        ) from None
