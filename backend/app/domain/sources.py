"""Owner-scoped immutable source attachment and verified previews."""

from __future__ import annotations

import io
import json
from hashlib import sha256
from typing import Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.source_schemas import SourceDetail, SourcePreview, SourcePreviewEnvelope
from app.core.config import Settings
from app.db.models import FileAsset, ReportSource
from app.db.repositories import (
    attach_source,
    finalize_idempotency,
    get_report,
    get_source,
    resolve_idempotency,
)
from app.db.session import transaction
from app.domain.assets import AssetServices, ResourceNotFound, _new_asset
from app.domain.reports import validate_idempotency_key
from app.processing.source_envelope import SourceEnvelopeError, csv_preview, parse_csv, text_preview
from app.storage.coordinator import StorageCoordinator
from app.storage.files import prepare_content
from app.storage.keys import TrustedKeyBuilder
from app.storage.names import safe_filename


def _detail(source: ReportSource) -> SourceDetail:
    return SourceDetail(
        id=source.id,
        report_id=source.report_id,
        source_type=cast(Literal["csv", "text"], source.source_type),
        byte_size=source.byte_size,
        checksum_sha256=source.checksum_sha256.hex(),
        media_type=source.media_type,
        encoding=source.encoding,
        original_filename_untrusted=source.original_filename,
        display_filename=source.display_filename,
        created_at=source.created_at,
    )


class SourceServices:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        coordinator: StorageCoordinator,
        keys: TrustedKeyBuilder,
        settings: Settings,
    ) -> None:
        self.sessions = sessions
        self.coordinator = coordinator
        self.keys = keys
        self.settings = settings

    async def _authorize(self, owner_id: UUID, report_id: UUID) -> None:
        async with transaction(self.sessions) as session:
            if await get_report(session, owner_id=owner_id, report_id=report_id) is None:
                raise ResourceNotFound

    async def _reserve(
        self, owner_id: UUID, report_id: UUID, operation: str, key: str, fingerprint: bytes
    ) -> UUID:
        validate_idempotency_key(key)
        async with transaction(self.sessions) as session:
            record = await resolve_idempotency(
                session,
                principal_id=owner_id,
                operation=operation,
                scope_kind="report",
                scope_id=report_id,
                raw_key=key,
                command_fingerprint=fingerprint,
            )
            return record.id

    async def _finalize(
        self,
        owner_id: UUID,
        report_id: UUID,
        operation: str,
        key: str,
        fingerprint: bytes,
        source: ReportSource,
        asset: FileAsset | None = None,
    ) -> tuple[SourceDetail, bool]:
        async with transaction(self.sessions) as session:
            record = await resolve_idempotency(
                session,
                principal_id=owner_id,
                operation=operation,
                scope_kind="report",
                scope_id=report_id,
                raw_key=key,
                command_fingerprint=fingerprint,
            )
            if record.result_id is not None:
                existing = await get_source(
                    session, owner_id=owner_id, report_id=report_id, source_id=record.result_id
                )
                if existing is None:
                    raise ResourceNotFound
                return _detail(existing), True
            report = await get_report(session, owner_id=owner_id, report_id=report_id)
            if report is None:
                raise ResourceNotFound
            await attach_source(
                session, owner_id=owner_id, report_id=report_id, source=source, asset=asset
            )
            await finalize_idempotency(
                session,
                record=record,
                result_type="source",
                result_id=source.id,
                success_status=201,
            )
            await session.flush()
            return _detail(source), False

    async def attach_text(
        self, owner_id: UUID, report_id: UUID, content: str, key: str
    ) -> tuple[SourceDetail, bool]:
        await self._authorize(owner_id, report_id)
        raw = content.encode("utf-8")
        if not raw:
            raise ValueError("empty text")
        if "\x00" in content:
            raise SourceEnvelopeError("validation_failed")
        if len(raw) > self.settings.source_text_max_bytes:
            raise SourceEnvelopeError("payload_too_large")
        fingerprint = sha256(json.dumps([content], ensure_ascii=False).encode()).digest()
        record_id = await self._reserve(owner_id, report_id, "attach-source-text", key, fingerprint)
        source = ReportSource(
            id=uuid5(NAMESPACE_URL, str(record_id)),
            owner_id=owner_id,
            report_id=report_id,
            source_type="text",
            checksum_sha256=sha256(raw).digest(),
            byte_size=len(raw),
            media_type="text/plain",
            encoding="utf-8",
            inline_text=content,
        )
        return await self._finalize(
            owner_id, report_id, "attach-source-text", key, fingerprint, source
        )

    async def attach_csv(
        self,
        owner_id: UUID,
        report_id: UUID,
        content: bytes,
        media_type: str,
        filename: str,
        key: str,
    ) -> tuple[SourceDetail, bool]:
        await self._authorize(owner_id, report_id)
        if "\x00" in filename:
            raise SourceEnvelopeError("validation_failed")
        parsed = parse_csv(
            content,
            max_bytes=self.settings.source_csv_max_bytes,
            max_records=self.settings.source_csv_max_records,
            media_type=media_type,
        )
        fingerprint = sha256(
            json.dumps([sha256(content).hexdigest(), media_type, filename]).encode()
        ).digest()
        record_id = await self._reserve(owner_id, report_id, "attach-source-csv", key, fingerprint)
        source_id = uuid5(NAMESPACE_URL, str(record_id))
        display = safe_filename(filename, default_stem="source", extension=".csv")
        prepared = await prepare_content(
            io.BytesIO(content),
            identity=self.keys.source_csv(
                owner_id=owner_id, report_id=report_id, source_id=source_id
            ),
            owner_id=owner_id,
            report_id=report_id,
            logical_id=source_id,
            safe_filename=display,
            content_type="text/csv",
            max_bytes=self.settings.source_csv_max_bytes,
        )
        try:
            source = ReportSource(
                id=source_id,
                owner_id=owner_id,
                report_id=report_id,
                source_type="csv",
                checksum_sha256=sha256(content).digest(),
                byte_size=len(content),
                media_type="text/csv",
                encoding=parsed.encoding,
                original_filename=filename,
                display_filename=display,
            )
            asset = _new_asset(prepared.metadata, safe_name=display)
            stored = None
            try:
                async with transaction(self.sessions) as session:
                    record = await resolve_idempotency(
                        session,
                        principal_id=owner_id,
                        operation="attach-source-csv",
                        scope_kind="report",
                        scope_id=report_id,
                        raw_key=key,
                        command_fingerprint=fingerprint,
                    )
                    if record.result_id is not None:
                        existing = await get_source(
                            session,
                            owner_id=owner_id,
                            report_id=report_id,
                            source_id=record.result_id,
                        )
                        if existing is None:
                            raise ResourceNotFound
                        return _detail(existing), True
                    stored = await self.coordinator.create_or_verify(prepared)
                    await attach_source(
                        session,
                        owner_id=owner_id,
                        report_id=report_id,
                        source=source,
                        asset=asset,
                    )
                    await finalize_idempotency(
                        session,
                        record=record,
                        result_type="source",
                        result_id=source.id,
                        success_status=201,
                    )
                    await session.flush()
                    result = _detail(source)
                return result, False
            except Exception:
                # Keep the reservation locked while deciding whether compensation is safe.
                async with transaction(self.sessions) as session:
                    record = await resolve_idempotency(
                        session,
                        principal_id=owner_id,
                        operation="attach-source-csv",
                        scope_kind="report",
                        scope_id=report_id,
                        raw_key=key,
                        command_fingerprint=fingerprint,
                    )
                    existing = await get_source(
                        session, owner_id=owner_id, report_id=report_id, source_id=source_id
                    )
                    if existing is not None:
                        return _detail(existing), True
                    if record.result_id is None and stored is not None:
                        await self.coordinator.compensate(stored)
                raise
        finally:
            prepared.close()

    async def detail(self, owner_id: UUID, report_id: UUID, source_id: UUID) -> SourceDetail:
        async with transaction(self.sessions) as session:
            if await get_report(session, owner_id=owner_id, report_id=report_id) is None:
                raise ResourceNotFound
            source = await get_source(
                session, owner_id=owner_id, report_id=report_id, source_id=source_id
            )
            if source is None:
                raise ResourceNotFound
            return _detail(source)

    async def preview(
        self, owner_id: UUID, report_id: UUID, source_id: UUID, asset_services: AssetServices
    ) -> SourcePreview:
        detail = await self.detail(owner_id, report_id, source_id)
        if detail.source_type == "text":
            async with transaction(self.sessions) as session:
                source = await get_source(
                    session, owner_id=owner_id, report_id=report_id, source_id=source_id
                )
                if source is None or source.inline_text is None:
                    raise ResourceNotFound
                projected = text_preview(
                    source.inline_text,
                    max_chars=self.settings.source_preview_max_text_chars,
                    max_response_bytes=self.settings.source_preview_max_response_bytes,
                )
        else:
            verified = await asset_services.retrieve_csv(
                owner_id=owner_id, report_id=report_id, source_id=source_id
            )
            try:
                original = verified.file.read()
            finally:
                verified.close()
            parsed = parse_csv(
                original,
                max_bytes=self.settings.source_csv_max_bytes,
                max_records=self.settings.source_csv_max_records,
            )
            projected = csv_preview(
                parsed,
                max_rows=self.settings.source_preview_max_rows,
                max_cell_chars=self.settings.source_preview_max_cell_chars,
                max_response_bytes=self.settings.source_preview_max_response_bytes,
            )
        preview = SourcePreview.model_validate(projected)
        while (
            len(SourcePreviewEnvelope(data=preview).model_dump_json().encode())
            > self.settings.source_preview_max_response_bytes
        ):
            if preview.source_type == "text" and preview.excerpt:
                preview.excerpt = preview.excerpt[:-1]
            elif preview.rows:
                preview.rows.pop()
            else:
                raise SourceEnvelopeError("payload_too_large")
            preview.truncated = True
        return preview
