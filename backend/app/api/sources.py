"""Authenticated source intake and bounded review endpoints."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.api.dependencies import (
    AuthenticatedPrincipal,
    get_asset_services,
    get_authenticated_principal,
)
from app.api.errors import APIError
from app.api.report_schemas import ErrorEnvelope
from app.api.source_schemas import PasteSourceRequest, SourceEnvelope, SourcePreviewEnvelope
from app.db.repositories import IdempotencyConflict
from app.domain.assets import AssetServices, ResourceNotFound
from app.domain.sources import SourceServices
from app.processing.source_envelope import SourceEnvelopeError
from app.storage.errors import StorageError

router = APIRouter(prefix="/api/v1/reports/{report_id}/sources", tags=["sources"])
errors: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorEnvelope} for code in (400, 401, 404, 409, 413, 415, 422, 503)
}
create_responses: dict[int | str, dict[str, Any]] = {
    **errors,
    201: {
        "model": SourceEnvelope,
        "headers": {
            "Idempotency-Replayed": {
                "description": "Present with value true when an earlier attachment is replayed.",
                "schema": {"type": "string", "enum": ["true"]},
            }
        },
    },
}


def services(request: Request) -> SourceServices:
    return cast(SourceServices, request.app.state.source_services)


def mapped(error: Exception) -> APIError:
    if isinstance(error, ResourceNotFound):
        return APIError(404, "resource_not_found", "The requested resource was not found.")
    if isinstance(error, IdempotencyConflict):
        return APIError(
            409, "idempotency_conflict", "The idempotency key was used for another command."
        )
    if isinstance(error, SourceEnvelopeError):
        status = {
            "payload_too_large": 413,
            "unsupported_media_type": 415,
            "unsupported_encoding": 415,
        }.get(error.code, 422)
        return APIError(status, error.code, "The source input is invalid.")
    if isinstance(error, StorageError):
        return APIError(
            503,
            "storage_unavailable",
            "The source is temporarily unavailable.",
            retryable=True,
            retry_after=5,
        )
    return APIError(400, "invalid_request", "The source request is invalid.")


@router.post("/text", status_code=201, response_model=SourceEnvelope, responses=create_responses)
async def attach_text(
    report_id: UUID,
    command: PasteSourceRequest,
    response: Response,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    service: Annotated[SourceServices, Depends(services)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> SourceEnvelope:
    try:
        detail, replayed = await service.attach_text(
            principal.id, report_id, command.content, idempotency_key
        )
    except (ResourceNotFound, IdempotencyConflict, SourceEnvelopeError, ValueError) as exc:
        raise mapped(exc) from None
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return SourceEnvelope(data=detail)


@router.post(
    "/csv",
    status_code=201,
    response_model=SourceEnvelope,
    responses=create_responses,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                        "additionalProperties": False,
                    }
                }
            },
        }
    },
)
async def attach_csv(
    report_id: UUID,
    request: Request,
    response: Response,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    service: Annotated[SourceServices, Depends(services)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> SourceEnvelope:
    try:
        if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
            raise SourceEnvelopeError("unsupported_media_type")

        async def bounded_stream() -> AsyncGenerator[bytes, None]:
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > service.settings.source_csv_max_bytes + 16_384:
                    raise SourceEnvelopeError("payload_too_large")
                yield chunk

        form = await MultiPartParser(
            request.headers, bounded_stream(), max_files=2, max_fields=0
        ).parse()
        files = list(form.getlist("file"))
        if len(files) != 1 or len(form) != 1 or not isinstance(files[0], UploadFile):
            raise ValueError("exactly one file is required")
        upload = files[0]
        content = upload.file.read(service.settings.source_csv_max_bytes + 1)
        await upload.close()
        detail, replayed = await service.attach_csv(
            principal.id,
            report_id,
            content,
            upload.content_type or "",
            upload.filename or "",
            idempotency_key,
        )
    except (
        ResourceNotFound,
        IdempotencyConflict,
        SourceEnvelopeError,
        ValueError,
        StorageError,
        MultiPartException,
    ) as exc:
        raise mapped(exc) from None
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return SourceEnvelope(data=detail)


@router.get("/{source_id}", response_model=SourceEnvelope, responses=errors)
async def get_source(
    report_id: UUID,
    source_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    service: Annotated[SourceServices, Depends(services)],
) -> SourceEnvelope:
    try:
        return SourceEnvelope(data=await service.detail(principal.id, report_id, source_id))
    except ResourceNotFound as exc:
        raise mapped(exc) from None


@router.get("/{source_id}/preview", response_model=SourcePreviewEnvelope, responses=errors)
async def get_preview(
    report_id: UUID,
    source_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    service: Annotated[SourceServices, Depends(services)],
    assets: Annotated[AssetServices, Depends(get_asset_services)],
) -> SourcePreviewEnvelope:
    try:
        return SourcePreviewEnvelope(
            data=await service.preview(principal.id, report_id, source_id, assets)
        )
    except (ResourceNotFound, SourceEnvelopeError, StorageError) as exc:
        raise mapped(exc) from None
