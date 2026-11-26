"""Owner-authorized storage/PostgreSQL choreography for CSV and PDF assets."""

from __future__ import annotations

from typing import BinaryIO, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import FileAsset, ReportSource
from app.db.repositories import (
    ConcurrencyConflict,
    PdfAssetAggregate,
    SourceAssetAggregate,
    file_asset_metadata_matches,
    finish_pdf_export,
    get_pdf_asset,
    get_report,
    get_source_asset,
    insert_or_load_csv_binding,
)
from app.db.session import transaction
from app.storage.coordinator import StorageCoordinator
from app.storage.errors import StorageError, StorageErrorCode
from app.storage.files import VerifiedContent, prepare_content
from app.storage.keys import TrustedKeyBuilder
from app.storage.names import safe_filename
from app.storage.types import (
    AppEnvironment,
    ObjectIdentity,
    ObjectMetadata,
    StoragePurpose,
    StoreResult,
)


class ResourceNotFound(RuntimeError):
    pass


class ExportNotReady(RuntimeError):
    def __init__(self, state: str) -> None:
        self.state = state
        super().__init__("export_not_ready")


def _new_asset(
    metadata: ObjectMetadata,
    *,
    safe_name: str,
    version_id: UUID | None = None,
    export_id: UUID | None = None,
) -> FileAsset:
    return FileAsset(
        owner_id=metadata.owner_id,
        report_id=metadata.report_id,
        purpose=metadata.identity.purpose.value,
        environment=metadata.identity.environment,
        bucket=metadata.identity.bucket,
        object_key=metadata.identity.key,
        safe_filename=safe_name,
        content_type=metadata.content_type,
        byte_size=metadata.byte_size,
        checksum_sha256=bytes.fromhex(metadata.checksum_sha256),
        version_id=version_id,
        export_id=export_id,
    )


def _metadata_from_asset(
    asset: FileAsset, purpose: StoragePurpose, logical_id: UUID
) -> ObjectMetadata:
    environments = {"local", "test", "development", "staging", "production"}
    if asset.environment not in environments or asset.purpose != purpose.value:
        raise StorageError(StorageErrorCode.INTEGRITY_FAILED)
    environment = cast(AppEnvironment, asset.environment)
    return ObjectMetadata(
        identity=ObjectIdentity(
            environment=environment,
            bucket=asset.bucket,
            key=asset.object_key,
            purpose=purpose,
        ),
        owner_id=asset.owner_id,
        report_id=asset.report_id,
        logical_id=logical_id,
        content_type=asset.content_type,
        byte_size=asset.byte_size,
        checksum_sha256=asset.checksum_sha256.hex(),
    )


class AssetServices:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        coordinator: StorageCoordinator,
        keys: TrustedKeyBuilder,
        source_csv_max_bytes: int,
        generated_pdf_max_bytes: int,
    ) -> None:
        self._sessions = sessions
        self._coordinator = coordinator
        self._keys = keys
        self._source_csv_max_bytes = source_csv_max_bytes
        self._generated_pdf_max_bytes = generated_pdf_max_bytes

    async def _compensate_after_failure(self, result: StoreResult) -> None:
        try:
            await self._coordinator.compensate(result)
        except StorageError:
            pass

    async def _reconcile_csv(
        self,
        *,
        owner_id: UUID,
        report_id: UUID,
        source: ReportSource,
        asset: FileAsset,
    ) -> SourceAssetAggregate | None:
        try:
            async with transaction(self._sessions) as session:
                existing = await get_source_asset(
                    session,
                    owner_id=owner_id,
                    report_id=report_id,
                    source_id=source.id,
                )
                if existing is None:
                    return None
                source_matches = (
                    existing.source.checksum_sha256 == source.checksum_sha256
                    and existing.source.byte_size == source.byte_size
                    and existing.source.media_type == source.media_type
                    and existing.source.encoding == source.encoding
                    and existing.source.original_filename == source.original_filename
                    and existing.source.display_filename == source.display_filename
                )
                if source_matches and file_asset_metadata_matches(existing.asset, asset):
                    return existing
        except Exception:
            return None
        return None

    async def _reconcile_pdf(
        self,
        *,
        owner_id: UUID,
        report_id: UUID,
        version_id: UUID,
        export_id: UUID,
        asset: FileAsset,
    ) -> FileAsset | None:
        try:
            async with transaction(self._sessions) as session:
                existing = await get_pdf_asset(
                    session,
                    owner_id=owner_id,
                    report_id=report_id,
                    version_id=version_id,
                    export_id=export_id,
                )
                if (
                    existing is not None
                    and existing.export.state == "succeeded"
                    and existing.asset is not None
                    and file_asset_metadata_matches(existing.asset, asset)
                ):
                    return existing.asset
        except Exception:
            return None
        return None

    async def store_csv(
        self,
        *,
        owner_id: UUID,
        report_id: UUID,
        source_id: UUID,
        original_filename: str,
        content: BinaryIO,
    ) -> SourceAssetAggregate:
        async with transaction(self._sessions) as session:
            if await get_report(session, owner_id=owner_id, report_id=report_id) is None:
                raise ResourceNotFound
        display_name = safe_filename(
            original_filename,
            default_stem="source",
            extension=".csv",
        )
        prepared = await prepare_content(
            content,
            identity=self._keys.source_csv(
                owner_id=owner_id,
                report_id=report_id,
                source_id=source_id,
            ),
            owner_id=owner_id,
            report_id=report_id,
            logical_id=source_id,
            safe_filename=display_name,
            content_type="text/csv",
            max_bytes=self._source_csv_max_bytes,
        )
        try:
            stored = await self._coordinator.create_or_verify(prepared)
            asset = _new_asset(prepared.metadata, safe_name=display_name)
            source = ReportSource(
                id=source_id,
                owner_id=owner_id,
                report_id=report_id,
                source_type="csv",
                checksum_sha256=bytes.fromhex(prepared.metadata.checksum_sha256),
                byte_size=prepared.metadata.byte_size,
                media_type="text/csv",
                encoding="utf-8",
                original_filename=original_filename,
                display_filename=display_name,
            )
            try:
                async with transaction(self._sessions) as session:
                    return await insert_or_load_csv_binding(
                        session,
                        owner_id=owner_id,
                        report_id=report_id,
                        source=source,
                        asset=asset,
                    )
            except Exception:
                reconciled = await self._reconcile_csv(
                    owner_id=owner_id,
                    report_id=report_id,
                    source=source,
                    asset=asset,
                )
                if reconciled is not None:
                    return reconciled
                await self._compensate_after_failure(stored)
                raise
        finally:
            prepared.close()

    async def store_generated_pdf(
        self,
        *,
        owner_id: UUID,
        report_id: UUID,
        version_id: UUID,
        export_id: UUID,
        input_identity: bytes,
        expected_attempt_count: int,
        content: BinaryIO,
    ) -> FileAsset:
        async with transaction(self._sessions) as session:
            aggregate = await get_pdf_asset(
                session,
                owner_id=owner_id,
                report_id=report_id,
                version_id=version_id,
                export_id=export_id,
            )
            if aggregate is None:
                raise ResourceNotFound
            if aggregate.export.input_identity != input_identity:
                raise ConcurrencyConflict("PDF input identity is stale")
            if aggregate.export.attempt_count != expected_attempt_count:
                raise ConcurrencyConflict("PDF attempt is stale")
            if aggregate.export.state not in {"running", "succeeded"}:
                raise ConcurrencyConflict("PDF completion state is stale")
            version_number = aggregate.version.version_number
        name = f"report-{version_number}.pdf"
        prepared = await prepare_content(
            content,
            identity=self._keys.generated_pdf(
                owner_id=owner_id,
                report_id=report_id,
                version_id=version_id,
                export_id=export_id,
                attempt_ordinal=expected_attempt_count,
            ),
            owner_id=owner_id,
            report_id=report_id,
            logical_id=export_id,
            safe_filename=name,
            content_type="application/pdf",
            max_bytes=self._generated_pdf_max_bytes,
        )
        try:
            stored = await self._coordinator.create_or_verify(prepared)
            asset = _new_asset(
                prepared.metadata,
                safe_name=name,
                version_id=version_id,
                export_id=export_id,
            )
            try:
                async with transaction(self._sessions) as session:
                    return await finish_pdf_export(
                        session,
                        owner_id=owner_id,
                        report_id=report_id,
                        export_id=export_id,
                        expected_attempt_count=expected_attempt_count,
                        asset=asset,
                    )
            except Exception:
                reconciled = await self._reconcile_pdf(
                    owner_id=owner_id,
                    report_id=report_id,
                    version_id=version_id,
                    export_id=export_id,
                    asset=asset,
                )
                if reconciled is not None:
                    return reconciled
                await self._compensate_after_failure(stored)
                raise
        finally:
            prepared.close()

    async def retrieve_csv(
        self,
        *,
        owner_id: UUID,
        report_id: UUID,
        source_id: UUID,
    ) -> VerifiedContent:
        async with transaction(self._sessions) as session:
            aggregate = await get_source_asset(
                session,
                owner_id=owner_id,
                report_id=report_id,
                source_id=source_id,
            )
            if aggregate is None:
                raise ResourceNotFound
            metadata = _metadata_from_asset(
                aggregate.asset,
                StoragePurpose.SOURCE_CSV,
                aggregate.source.id,
            )
            filename = aggregate.asset.safe_filename
        return await self._coordinator.retrieve_verified(
            expected=metadata,
            safe_filename=filename,
            max_bytes=self._source_csv_max_bytes,
        )

    async def retrieve_pdf(
        self,
        *,
        owner_id: UUID,
        report_id: UUID,
        version_id: UUID,
        export_id: UUID,
    ) -> VerifiedContent:
        async with transaction(self._sessions) as session:
            aggregate: PdfAssetAggregate | None = await get_pdf_asset(
                session,
                owner_id=owner_id,
                report_id=report_id,
                version_id=version_id,
                export_id=export_id,
            )
            if aggregate is None:
                raise ResourceNotFound
            if aggregate.export.state != "succeeded":
                raise ExportNotReady(aggregate.export.state)
            if aggregate.asset is None:
                raise StorageError(StorageErrorCode.INTEGRITY_FAILED)
            metadata = _metadata_from_asset(
                aggregate.asset,
                StoragePurpose.GENERATED_PDF,
                aggregate.export.id,
            )
            filename = aggregate.asset.safe_filename
        return await self._coordinator.retrieve_verified(
            expected=metadata,
            safe_filename=filename,
            max_bytes=self._generated_pdf_max_bytes,
        )
