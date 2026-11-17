"""Authorized, integrity-verified PDF download route."""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.api.dependencies import (
    AuthenticatedPrincipal,
    get_asset_services,
    get_authenticated_principal,
)
from app.api.errors import APIError
from app.domain.assets import AssetServices, ExportNotReady, ResourceNotFound
from app.storage.errors import StorageError, StorageErrorCode
from app.storage.files import VerifiedContent
from app.storage.names import attachment_content_disposition

router = APIRouter(prefix="/api/v1", tags=["pdf-exports"])


def _stream_verified(content: VerifiedContent) -> Generator[bytes, None, None]:
    try:
        while chunk := content.file.read(64 * 1024):
            yield chunk
    finally:
        content.close()


@router.get(
    "/reports/{report_id}/versions/{version_id}/pdf-exports/{export_id}/download",
    response_class=StreamingResponse,
)
async def download_pdf(
    report_id: UUID,
    version_id: UUID,
    export_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    services: Annotated[AssetServices, Depends(get_asset_services)],
) -> StreamingResponse:
    try:
        verified = await services.retrieve_pdf(
            owner_id=principal.id,
            report_id=report_id,
            version_id=version_id,
            export_id=export_id,
        )
    except ResourceNotFound:
        raise APIError(
            status_code=404,
            code="resource_not_found",
            message="The requested PDF export was not found.",
            context={"resource_type": "pdf_export"},
        ) from None
    except ExportNotReady as error:
        raise APIError(
            status_code=409,
            code="export_not_ready",
            message="The PDF export is not ready for download.",
            retryable=error.state in {"queued", "running"},
            context={"state": error.state},
        ) from None
    except StorageError as error:
        if error.code is StorageErrorCode.INTEGRITY_FAILED:
            raise APIError(
                status_code=500,
                code="internal_error",
                message="The PDF could not be verified.",
            ) from None
        raise APIError(
            status_code=503,
            code="dependency_unavailable",
            message="The PDF is temporarily unavailable.",
            retryable=True,
            retry_after=1,
        ) from None
    return StreamingResponse(
        _stream_verified(verified),
        status_code=200,
        media_type="application/pdf",
        headers={
            "Content-Length": str(verified.metadata.byte_size),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Disposition": attachment_content_disposition(verified.safe_filename),
        },
        background=BackgroundTask(verified.close),
    )
