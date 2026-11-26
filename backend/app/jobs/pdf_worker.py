"""Durable version-only PDF execution and stale-attempt recovery."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import PdfExport
from app.db.repositories import (
    ConcurrencyConflict,
    claim_pdf_export,
    fail_pdf_export,
    get_version,
    stale_running_pdf_attempts,
)
from app.db.session import create_session_factory, transaction
from app.domain.assets import AssetServices
from app.jobs.celery_app import celery_app
from app.pdf.errors import PdfRenderFailure
from app.pdf.renderer import PdfRenderer, validate_pdf_bytes
from app.pdf.version import SavedVersion
from app.storage.coordinator import StorageCoordinator
from app.storage.errors import StorageError
from app.storage.keys import TrustedKeyBuilder
from app.storage.s3 import S3ObjectStorage

Render = Callable[[SavedVersion], Awaitable[bytes]]


async def execute_pdf(
    sessions: async_sessionmaker[AsyncSession],
    assets: AssetServices,
    owner_id: UUID,
    report_id: UUID,
    export_id: UUID,
    ordinal: int,
    render: Render,
    max_bytes: int = 25_165_824,
) -> bool:
    async with transaction(sessions) as session:
        claimed = await claim_pdf_export(
            session,
            owner_id=owner_id,
            report_id=report_id,
            export_id=export_id,
            expected_attempt_count=ordinal,
        )
    if not claimed:
        return False
    boundary = "render"
    try:
        async with sessions() as session:
            export = await session.scalar(
                select(PdfExport).where(
                    PdfExport.id == export_id,
                    PdfExport.owner_id == owner_id,
                    PdfExport.report_id == report_id,
                )
            )
            if export is None or export.attempt_count != ordinal:
                raise PdfRenderFailure("invalid_snapshot")
            version = await get_version(
                session,
                owner_id=owner_id,
                report_id=report_id,
                version_id=export.version_id,
            )
            if (
                version is None
                or export.snapshot_identity != version.snapshot_identity
                or export.template_version != version.template_version
                or export.input_identity
                != sha256(version.snapshot_identity + version.template_version.encode()).digest()
            ):
                raise PdfRenderFailure("invalid_snapshot")
            saved = SavedVersion.from_record(version)
            input_identity = bytes(export.input_identity)
            version_id = version.id
        saved.validated_snapshot()
        data = validate_pdf_bytes(await render(saved), max_bytes)
        boundary = "storage"
        await assets.store_generated_pdf(
            owner_id=owner_id,
            report_id=report_id,
            version_id=version_id,
            export_id=export_id,
            input_identity=input_identity,
            expected_attempt_count=ordinal,
            content=BytesIO(data),
        )
    except Exception as error:
        code: str
        if isinstance(error, PdfRenderFailure):
            code = error.code
            retryable = code in {"render_failed", "renderer_timeout"}
        elif isinstance(error, (StorageError,)) or boundary == "storage":
            code, retryable = "storage_unavailable", True
        else:
            code, retryable = "render_failed", True
        try:
            async with transaction(sessions) as session:
                await fail_pdf_export(
                    session,
                    owner_id=owner_id,
                    report_id=report_id,
                    export_id=export_id,
                    expected_attempt_count=ordinal,
                    failure_code=code,
                    failure_message={
                        "invalid_snapshot": "The saved report version cannot be rendered.",
                        "artifact_validation_failed": "The generated PDF is invalid.",
                        "renderer_timeout": "The report PDF timed out.",
                        "render_failed": "The report PDF could not be rendered.",
                        "storage_unavailable": "The generated PDF could not be stored.",
                    }[code],
                    retryable=retryable,
                )
        except ConcurrencyConflict:
            return False
    return True


async def fail_stale_running_pdf(
    sessions: async_sessionmaker[AsyncSession],
    timeout_seconds: int,
    limit: int = 100,
) -> int:
    cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
    async with sessions() as session:
        stale = await stale_running_pdf_attempts(session, before=cutoff, limit=limit)
    failed = 0
    for owner_id, report_id, export_id, ordinal in stale:
        try:
            async with transaction(sessions) as session:
                await fail_pdf_export(
                    session,
                    owner_id=owner_id,
                    report_id=report_id,
                    export_id=export_id,
                    expected_attempt_count=ordinal,
                    failure_code="renderer_timeout",
                    failure_message="The report PDF timed out.",
                    retryable=True,
                )
            failed += 1
        except ConcurrencyConflict:
            pass
    return failed


@celery_app.task(name="pdf.execute", ignore_result=True)  # type: ignore[misc]
def pdf_task(owner_id: str, report_id: str, export_id: str, ordinal: int) -> None:
    settings = Settings()

    async def run() -> None:
        from app.core.resources import create_resource_clients

        clients = create_resource_clients(settings)
        try:
            sessions = create_session_factory(clients.postgresql)
            assets = AssetServices(
                sessions=sessions,
                coordinator=StorageCoordinator(S3ObjectStorage(clients.object_storage)),
                keys=TrustedKeyBuilder(settings.app_env, settings.s3_bucket),
                source_csv_max_bytes=settings.source_csv_max_bytes,
                generated_pdf_max_bytes=settings.generated_pdf_max_bytes,
            )
            await execute_pdf(
                sessions,
                assets,
                UUID(owner_id),
                UUID(report_id),
                UUID(export_id),
                ordinal,
                PdfRenderer(settings).render,
                settings.generated_pdf_max_bytes,
            )
        finally:
            await clients.close()

    asyncio.run(run())
