"""Owner-scoped PDF export commands and status reads."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response

from app.api.dependencies import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    get_pdf_export_services,
)
from app.api.errors import APIError
from app.api.report_schemas import ErrorEnvelope
from app.api.version_schemas import (
    CreatePdfExportRequest,
    PdfExportEnvelope,
    PdfExportListEnvelope,
    RetryPdfExportRequest,
)
from app.db.repositories import ConcurrencyConflict, IdempotencyConflict, JobNotRetryable
from app.domain.assets import ResourceNotFound
from app.domain.pdf_exports import PdfExportServices
from app.domain.reports import InvalidCursor

router = APIRouter(
    prefix="/api/v1/reports/{report_id}/versions/{version_id}/pdf-exports",
    tags=["pdf-exports"],
)
errors: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorEnvelope} for code in (400, 401, 404, 409, 422)
}


def _not_found() -> APIError:
    return APIError(404, "resource_not_found", "The requested resource was not found.")


def _map_error(error: Exception) -> APIError:
    if isinstance(error, ResourceNotFound):
        return _not_found()
    if isinstance(error, IdempotencyConflict):
        return APIError(
            409, "idempotency_conflict", "The idempotency key was used for another command."
        )
    if isinstance(error, ConcurrencyConflict):
        return APIError(409, "revision_conflict", "The PDF export state or input has changed.")
    if isinstance(error, JobNotRetryable):
        return APIError(409, "job_not_retryable", "The PDF export cannot be retried.")
    if isinstance(error, InvalidCursor):
        return APIError(400, "invalid_cursor", "The cursor is invalid.")
    return APIError(400, "invalid_request", "The PDF export request is invalid.")


@router.post("", status_code=202, response_model=PdfExportEnvelope, responses=errors)
async def create_pdf_export(
    report_id: UUID,
    version_id: UUID,
    command: CreatePdfExportRequest,
    response: Response,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[PdfExportServices, Depends(get_pdf_export_services)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> PdfExportEnvelope:
    try:
        detail, replayed = await services.create(
            principal.id, report_id, version_id, command, idempotency_key
        )
    except (
        ResourceNotFound,
        IdempotencyConflict,
        ConcurrencyConflict,
        JobNotRetryable,
        ValueError,
    ) as error:
        raise _map_error(error) from None
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return PdfExportEnvelope(data=detail)


@router.get("", response_model=PdfExportListEnvelope, responses=errors)
async def list_pdf_exports(
    report_id: UUID,
    version_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[PdfExportServices, Depends(get_pdf_export_services)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
) -> PdfExportListEnvelope:
    try:
        data, page = await services.list(principal.id, report_id, version_id, limit, cursor)
    except (ResourceNotFound, InvalidCursor) as error:
        raise _map_error(error) from None
    return PdfExportListEnvelope(data=data, page=page)


@router.get("/{export_id}", response_model=PdfExportEnvelope, responses=errors)
async def get_pdf_export(
    report_id: UUID,
    version_id: UUID,
    export_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[PdfExportServices, Depends(get_pdf_export_services)],
) -> PdfExportEnvelope:
    try:
        return PdfExportEnvelope(
            data=await services.detail(principal.id, report_id, version_id, export_id)
        )
    except ResourceNotFound:
        raise _not_found() from None


@router.post(
    "/{export_id}/retry", status_code=202, response_model=PdfExportEnvelope, responses=errors
)
async def retry_pdf_export(
    report_id: UUID,
    version_id: UUID,
    export_id: UUID,
    command: RetryPdfExportRequest,
    response: Response,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[PdfExportServices, Depends(get_pdf_export_services)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> PdfExportEnvelope:
    try:
        detail, replayed = await services.retry(
            principal.id, report_id, version_id, export_id, command, idempotency_key
        )
    except (
        ResourceNotFound,
        IdempotencyConflict,
        ConcurrencyConflict,
        JobNotRetryable,
        ValueError,
    ) as error:
        raise _map_error(error) from None
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return PdfExportEnvelope(data=detail)
