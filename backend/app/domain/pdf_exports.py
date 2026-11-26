"""Owner-scoped commands and public projections for immutable PDF exports."""

from __future__ import annotations

import base64
import hmac
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.report_schemas import Page
from app.api.version_schemas import (
    CreatePdfExportRequest,
    PdfExportAttemptDetail,
    PdfExportDetail,
    PdfExportFailure,
    PdfExportFile,
    PdfExportSummary,
    RetryPdfExportRequest,
)
from app.db.models import FileAsset, PdfExport, PdfExportAttempt, ReportVersion
from app.db.repositories import (
    ConcurrencyConflict,
    IdempotencyConflict,
    create_pdf_export,
    finalize_idempotency,
    get_pdf_export,
    get_report,
    get_version,
    list_pdf_exports_page,
    queued_pdf_attempts,
    resolve_idempotency,
    retry_pdf_export,
)
from app.db.session import transaction
from app.domain.assets import ResourceNotFound
from app.domain.reports import InvalidCursor, validate_idempotency_key
from app.pdf.version import SUPPORTED_TEMPLATE

Publisher = Callable[[UUID, UUID, UUID, int], None]
PdfState = Literal["queued", "running", "succeeded", "failed"]
logger = logging.getLogger(__name__)


def publish_pdf_attempt(owner_id: UUID, report_id: UUID, export_id: UUID, ordinal: int) -> None:
    from app.core.config import Settings
    from app.jobs.celery_app import celery_app, configure_celery

    configure_celery(celery_app, Settings())
    celery_app.send_task(
        "pdf.execute", args=[str(owner_id), str(report_id), str(export_id), ordinal], retry=False
    )


def _failure(
    code: str | None, message: str | None, retryable: bool | None
) -> PdfExportFailure | None:
    if code is None or message is None or retryable is None:
        return None
    return PdfExportFailure(code=code, message=message, retryable=retryable)


def _summary(export: PdfExport) -> PdfExportSummary:
    return PdfExportSummary(
        id=export.id,
        report_id=export.report_id,
        version_id=export.version_id,
        template_version=export.template_version,
        input_identity=export.input_identity.hex(),
        state=cast(PdfState, export.state),
        attempt_count=export.attempt_count,
        created_at=export.created_at,
        updated_at=export.updated_at,
        failure=_failure(export.failure_code, export.failure_message, export.failure_retryable),
    )


async def _detail(session: AsyncSession, export: PdfExport) -> PdfExportDetail:
    attempts = list(
        (
            await session.scalars(
                select(PdfExportAttempt)
                .where(
                    PdfExportAttempt.owner_id == export.owner_id,
                    PdfExportAttempt.report_id == export.report_id,
                    PdfExportAttempt.export_id == export.id,
                )
                .order_by(PdfExportAttempt.attempt_ordinal)
            )
        ).all()
    )
    asset = None
    if export.state == "succeeded" and export.generated_asset_id is not None:
        asset = await session.scalar(
            select(FileAsset).where(
                FileAsset.id == export.generated_asset_id,
                FileAsset.owner_id == export.owner_id,
                FileAsset.report_id == export.report_id,
                FileAsset.export_id == export.id,
                FileAsset.version_id == export.version_id,
            )
        )
    return PdfExportDetail(
        **_summary(export).model_dump(),
        attempts=[
            PdfExportAttemptDetail(
                ordinal=row.attempt_ordinal,
                state=cast(PdfState, row.state),
                queued_at=row.queued_at,
                started_at=row.started_at,
                finished_at=row.finished_at,
                failure=_failure(row.failure_code, row.failure_message, row.failure_retryable),
            )
            for row in attempts
        ],
        file=(
            PdfExportFile(
                filename=asset.safe_filename,
                content_type="application/pdf",
                byte_size=asset.byte_size,
                checksum=asset.checksum_sha256.hex(),
                download_available=True,
            )
            if asset is not None
            else None
        ),
    )


class PdfExportServices:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cursor_secret: str,
        publisher: Publisher = publish_pdf_attempt,
    ) -> None:
        self.sessions = sessions
        self.secret = cursor_secret.encode()
        self.publisher = publisher

    async def _version(
        self, session: AsyncSession, owner_id: UUID, report_id: UUID, version_id: UUID
    ) -> ReportVersion:
        if await get_report(session, owner_id=owner_id, report_id=report_id) is None:
            raise ResourceNotFound
        version = await get_version(
            session, owner_id=owner_id, report_id=report_id, version_id=version_id
        )
        if version is None:
            raise ResourceNotFound
        return version

    async def _export(
        self,
        session: AsyncSession,
        owner_id: UUID,
        report_id: UUID,
        version_id: UUID,
        export_id: UUID,
    ) -> PdfExport:
        export = await get_pdf_export(
            session, owner_id=owner_id, report_id=report_id, export_id=export_id
        )
        if export is None or export.version_id != version_id:
            raise ResourceNotFound
        return export

    def _dispatch(self, owner_id: UUID, report_id: UUID, export_id: UUID, ordinal: int) -> None:
        try:
            self.publisher(owner_id, report_id, export_id, ordinal)
        except Exception:
            logger.warning(
                "PDF delivery pending recovery: export_id=%s ordinal=%d", export_id, ordinal
            )

    async def create(
        self,
        owner_id: UUID,
        report_id: UUID,
        version_id: UUID,
        command: CreatePdfExportRequest,
        key: str,
    ) -> tuple[PdfExportDetail, bool]:
        fingerprint = sha256(f"{version_id}:{command.template_version}".encode()).digest()
        async with transaction(self.sessions) as session:
            version = await self._version(session, owner_id, report_id, version_id)
            validate_idempotency_key(key)
            if (
                command.template_version != SUPPORTED_TEMPLATE
                or command.template_version != version.template_version
            ):
                raise ValueError("PDF template does not match saved version")
            record = await resolve_idempotency(
                session,
                principal_id=owner_id,
                operation="create-pdf-export",
                scope_kind="report_version",
                scope_id=version_id,
                raw_key=key,
                command_fingerprint=fingerprint,
            )
            replayed = record.result_id is not None
            existed = await session.scalar(
                select(PdfExport.id).where(
                    PdfExport.version_id == version_id,
                    PdfExport.snapshot_identity == version.snapshot_identity,
                    PdfExport.template_version == version.template_version,
                )
            )
            export = await create_pdf_export(
                session,
                owner_id=owner_id,
                report_id=report_id,
                version_id=version_id,
                input_identity=sha256(
                    version.snapshot_identity + version.template_version.encode()
                ).digest(),
            )
            if replayed and (record.result_type != "pdf_export" or record.result_id != export.id):
                raise IdempotencyConflict("PDF idempotency target changed")
            await finalize_idempotency(
                session,
                record=record,
                result_type="pdf_export",
                result_id=export.id,
                success_status=202,
            )
            detail = await _detail(session, export)
        if existed is None and export.state == "queued":
            self._dispatch(owner_id, report_id, export.id, export.attempt_count)
        return detail, replayed

    async def detail(
        self, owner_id: UUID, report_id: UUID, version_id: UUID, export_id: UUID
    ) -> PdfExportDetail:
        async with self.sessions() as session:
            await self._version(session, owner_id, report_id, version_id)
            return await _detail(
                session, await self._export(session, owner_id, report_id, version_id, export_id)
            )

    def _encode_cursor(
        self, owner_id: UUID, report_id: UUID, version_id: UUID, export: PdfExport
    ) -> str:
        body = dict(
            v=1,
            owner=str(owner_id),
            report=str(report_id),
            version=str(version_id),
            route="pdf-exports",
            order="created_at:desc,id:desc",
            created_at=export.created_at.astimezone(UTC).isoformat(),
            id=str(export.id),
            expires_at=int((datetime.now(UTC) + timedelta(hours=24)).timestamp()),
        )
        payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        return (
            base64.urlsafe_b64encode(payload + hmac.new(self.secret, payload, sha256).digest())
            .decode()
            .rstrip("=")
        )

    def _decode_cursor(
        self, owner_id: UUID, report_id: UUID, version_id: UUID, cursor: str
    ) -> tuple[datetime, UUID]:
        try:
            if not cursor or len(cursor) > 2048:
                raise ValueError
            raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(raw).decode().rstrip("=") != cursor or len(raw) <= 32:
                raise ValueError
            payload, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(signature, hmac.new(self.secret, payload, sha256).digest()):
                raise ValueError
            body = json.loads(payload)
            if (
                body["v"] != 1
                or body["owner"] != str(owner_id)
                or body["report"] != str(report_id)
                or body["version"] != str(version_id)
                or body["route"] != "pdf-exports"
                or body["order"] != "created_at:desc,id:desc"
                or type(body["expires_at"]) is not int
                or body["expires_at"] <= int(datetime.now(UTC).timestamp())
            ):
                raise ValueError
            instant = datetime.fromisoformat(body["created_at"])
            if instant.tzinfo is None:
                raise ValueError
            return instant, UUID(body["id"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidCursor from error

    async def list(
        self,
        owner_id: UUID,
        report_id: UUID,
        version_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[PdfExportSummary], Page]:
        async with self.sessions() as session:
            await self._version(session, owner_id, report_id, version_id)
            before = (
                self._decode_cursor(owner_id, report_id, version_id, cursor)
                if cursor is not None
                else None
            )
            rows = list(
                await list_pdf_exports_page(
                    session,
                    owner_id=owner_id,
                    report_id=report_id,
                    version_id=version_id,
                    limit=limit,
                    before=before,
                )
            )
            visible = rows[:limit]
            has_more = len(rows) > limit
            return [_summary(row) for row in visible], Page(
                limit=limit,
                has_more=has_more,
                next_cursor=self._encode_cursor(owner_id, report_id, version_id, visible[-1])
                if has_more
                else None,
            )

    async def retry(
        self,
        owner_id: UUID,
        report_id: UUID,
        version_id: UUID,
        export_id: UUID,
        command: RetryPdfExportRequest,
        key: str,
    ) -> tuple[PdfExportDetail, bool]:
        fingerprint = sha256(
            f"{export_id}:{command.input_identity}:{command.expected_attempt_count}".encode()
        ).digest()
        async with transaction(self.sessions) as session:
            version = await self._version(session, owner_id, report_id, version_id)
            export = await self._export(session, owner_id, report_id, version_id, export_id)
            validate_idempotency_key(key)
            record = await resolve_idempotency(
                session,
                principal_id=owner_id,
                operation="retry-pdf-export",
                scope_kind="pdf_export",
                scope_id=export_id,
                raw_key=key,
                command_fingerprint=fingerprint,
            )
            replayed = record.result_id is not None
            if replayed:
                if record.result_type != "pdf_export" or record.result_id != export_id:
                    raise IdempotencyConflict("PDF retry target changed")
            else:
                expected = sha256(
                    version.snapshot_identity + version.template_version.encode()
                ).digest()
                if (
                    command.input_identity != expected.hex()
                    or export.input_identity != expected
                    or export.snapshot_identity != version.snapshot_identity
                    or export.template_version != version.template_version
                ):
                    raise ConcurrencyConflict("PDF input identity is stale")
                await retry_pdf_export(
                    session,
                    owner_id=owner_id,
                    report_id=report_id,
                    export_id=export_id,
                    expected_attempt_count=command.expected_attempt_count,
                )
                await finalize_idempotency(
                    session,
                    record=record,
                    result_type="pdf_export",
                    result_id=export_id,
                    success_status=202,
                )
                await session.refresh(export)
            detail = await _detail(session, export)
        if not replayed and export.state == "queued":
            self._dispatch(owner_id, report_id, export_id, export.attempt_count)
        return detail, replayed

    async def reconcile(self, limit: int = 100) -> int:
        async with self.sessions() as session:
            pending = await queued_pdf_attempts(session, limit=limit)
        for owner_id, report_id, export_id, ordinal in pending:
            self._dispatch(owner_id, report_id, export_id, ordinal)
        return len(pending)
