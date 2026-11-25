"""Owner-scoped mapping revisions and full CSV review."""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.source_schemas import (
    ColumnMapping,
    ImportConfigurationDetail,
    ImportConfigurationRequest,
    ImportValidationDetail,
    ValidateImportRequest,
    ValidationIssue,
)
from app.core.config import Settings
from app.db.models import (
    ImportColumnMapping,
    ImportConfigurationRevision,
    ImportValidation,
    Report,
)
from app.db.repositories import (
    ConcurrencyConflict,
    append_import_revision,
    create_import_configuration,
    get_import_configuration,
    get_import_validation,
    get_source,
    persist_import_validation,
)
from app.db.session import transaction
from app.domain.assets import AssetServices, ResourceNotFound
from app.processing.csv_import import validate_csv
from app.processing.source_envelope import parse_csv


class InvalidMapping(ValueError):
    def __init__(self, details: list[dict[str, object]]) -> None:
        self.details = details
        super().__init__("invalid mapping")


class ReviewResponseTooLarge(ValueError):
    """The complete issue list exceeds the safe response bound."""


def _mapping_details(mappings: list[ColumnMapping], column_count: int) -> list[dict[str, object]]:
    details: list[dict[str, object]] = []
    ordinals: set[int] = set()
    fields: set[str] = set()
    for index, mapping in enumerate(mappings):
        path = ["mappings", index]
        if mapping.source_column_ordinal >= column_count:
            details.append(
                {
                    "code": "invalid_field",
                    "message": "The column ordinal is outside the source.",
                    "path": [*path, "source_column_ordinal"],
                }
            )
        if mapping.source_column_ordinal in ordinals:
            details.append(
                {
                    "code": "duplicate_mapping",
                    "message": "A column is mapped twice.",
                    "path": [*path, "source_column_ordinal"],
                }
            )
        if mapping.canonical_field in fields:
            details.append(
                {
                    "code": "duplicate_mapping",
                    "message": "A field is mapped twice.",
                    "path": [*path, "canonical_field"],
                }
            )
        ordinals.add(mapping.source_column_ordinal)
        fields.add(mapping.canonical_field)
    return details


class ImportReviewServices:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.sessions = sessions
        self.settings = settings

    async def _current(
        self,
        session: AsyncSession,
        owner_id: UUID,
        report_id: UUID,
        source_id: UUID,
        *,
        lock: bool = False,
    ) -> tuple[Report, bytes]:
        query = select(Report).where(
            Report.id == report_id,
            Report.owner_id == owner_id,
            Report.current_source_id == source_id,
        )
        report = await session.scalar(query.with_for_update() if lock else query)
        if report is None:
            raise ResourceNotFound
        source = await get_source(
            session, owner_id=owner_id, report_id=report_id, source_id=source_id
        )
        if source is None or source.source_type != "csv":
            raise ResourceNotFound
        return report, source.checksum_sha256

    async def _bytes(
        self, assets: AssetServices, owner_id: UUID, report_id: UUID, source_id: UUID
    ) -> bytes:
        verified = await assets.retrieve_csv(
            owner_id=owner_id, report_id=report_id, source_id=source_id
        )
        try:
            return verified.file.read()
        finally:
            verified.close()

    async def put_configuration(
        self,
        owner_id: UUID,
        report_id: UUID,
        source_id: UUID,
        command: ImportConfigurationRequest,
        assets: AssetServices,
    ) -> ImportConfigurationDetail:
        async with transaction(self.sessions) as session:
            _, checksum = await self._current(session, owner_id, report_id, source_id)
        original = await self._bytes(assets, owner_id, report_id, source_id)
        envelope = parse_csv(
            original,
            max_bytes=self.settings.source_csv_max_bytes,
            max_records=self.settings.source_csv_max_records,
        )
        details = _mapping_details(command.mappings, len(envelope.columns))
        if details:
            raise InvalidMapping(details)
        mappings = [(m.source_column_ordinal, m.canonical_field) for m in command.mappings]
        async with transaction(self.sessions) as session:
            try:
                _, current_checksum = await self._current(
                    session, owner_id, report_id, source_id, lock=True
                )
            except ResourceNotFound as exc:
                raise ConcurrencyConflict("source changed") from exc
            if current_checksum != checksum:
                raise ConcurrencyConflict("source changed")
            config = await get_import_configuration(
                session, owner_id=owner_id, report_id=report_id, source_id=source_id
            )
            if config is None:
                if command.expected_revision != 0:
                    raise ConcurrencyConflict("configuration revision is stale")
                config = await create_import_configuration(
                    session,
                    owner_id=owner_id,
                    report_id=report_id,
                    source_id=source_id,
                    normalization_policy_version=command.normalization_policy_version,
                    date_format=command.date_format,
                    mappings=mappings,
                )
            else:
                if command.expected_revision == 0:
                    raise ConcurrencyConflict("configuration revision is stale")
                await append_import_revision(
                    session,
                    configuration_id=config.id,
                    owner_id=owner_id,
                    report_id=report_id,
                    expected_revision=command.expected_revision,
                    normalization_policy_version=command.normalization_policy_version,
                    date_format=command.date_format,
                    mappings=mappings,
                )
            return ImportConfigurationDetail(
                id=config.id,
                report_id=report_id,
                source_id=source_id,
                revision=config.current_revision,
                normalization_policy_version=command.normalization_policy_version,
                date_format=command.date_format,
                mappings=command.mappings,
            )

    async def validate(
        self,
        owner_id: UUID,
        report_id: UUID,
        source_id: UUID,
        command: ValidateImportRequest,
        assets: AssetServices,
    ) -> ImportValidationDetail:
        async with transaction(self.sessions) as session:
            report, checksum = await self._current(session, owner_id, report_id, source_id)
            config = await get_import_configuration(
                session, owner_id=owner_id, report_id=report_id, source_id=source_id
            )
            if config is None or config.current_revision != command.expected_revision:
                raise ConcurrencyConflict("configuration revision is stale")
            revision = await session.scalar(
                select(ImportConfigurationRevision).where(
                    ImportConfigurationRevision.configuration_id == config.id,
                    ImportConfigurationRevision.revision == config.current_revision,
                    ImportConfigurationRevision.owner_id == owner_id,
                    ImportConfigurationRevision.report_id == report_id,
                )
            )
            if revision is None:
                raise ConcurrencyConflict("configuration revision is stale")
            rows = list(
                (
                    await session.scalars(
                        select(ImportColumnMapping)
                        .where(
                            ImportColumnMapping.configuration_id == config.id,
                            ImportColumnMapping.revision == config.current_revision,
                            ImportColumnMapping.owner_id == owner_id,
                            ImportColumnMapping.report_id == report_id,
                        )
                        .order_by(ImportColumnMapping.source_column_ordinal)
                    )
                ).all()
            )
            mappings = [(row.source_column_ordinal, row.canonical_field) for row in rows]
            captured = (report.period_start, report.period_end, report.period_revision)
            config_id = config.id
            policy = revision.normalization_policy_version
            date_format = revision.date_format
        original = await self._bytes(assets, owner_id, report_id, source_id)
        envelope = parse_csv(
            original,
            max_bytes=self.settings.source_csv_max_bytes,
            max_records=self.settings.source_csv_max_records,
        )
        issues = validate_csv(
            envelope,
            mappings,
            date_format=date_format,
            period_start=captured[0],
            period_end=captured[1],
        )
        async with transaction(self.sessions) as session:
            try:
                report, current_checksum = await self._current(
                    session, owner_id, report_id, source_id, lock=True
                )
            except ResourceNotFound as exc:
                raise ConcurrencyConflict("source changed") from exc
            current = await get_import_configuration(
                session, owner_id=owner_id, report_id=report_id, source_id=source_id
            )
            if (
                current is None
                or current.id != config_id
                or current.current_revision != command.expected_revision
                or current_checksum != checksum
                or (report.period_start, report.period_end, report.period_revision) != captured
            ):
                raise ConcurrencyConflict("review input changed")
            existing = await session.scalar(
                select(ImportValidation)
                .where(
                    ImportValidation.owner_id == owner_id,
                    ImportValidation.report_id == report_id,
                    ImportValidation.configuration_id == config_id,
                    ImportValidation.revision == command.expected_revision,
                    ImportValidation.source_checksum == checksum,
                    ImportValidation.period_revision == captured[2],
                    ImportValidation.period_start == captured[0],
                    ImportValidation.period_end == captured[1],
                )
                .order_by(ImportValidation.created_at.desc())
                .limit(1)
            )
            if existing is None:
                existing = await persist_import_validation(
                    session,
                    owner_id=owner_id,
                    report_id=report_id,
                    configuration_id=config_id,
                    revision=command.expected_revision,
                    source_checksum=checksum,
                    period_start=captured[0],
                    period_end=captured[1],
                    period_revision=captured[2],
                    total_records=len(envelope.records),
                    issues=[item.as_dict() for item in issues],
                )
            loaded = await get_import_validation(
                session, owner_id=owner_id, report_id=report_id, validation_id=existing.id
            )
            assert loaded is not None
            result, persisted_issues = loaded
            detail = ImportValidationDetail(
                id=result.id,
                report_id=report_id,
                source_id=source_id,
                configuration_id=config_id,
                revision=result.revision,
                source_checksum_sha256=checksum.hex(),
                normalization_policy_version=policy,
                period_start=captured[0],
                period_end=captured[1],
                period_revision=captured[2],
                total_records=cast(int, result.total_records),
                accepted_row_count=0,
                rejected_row_count=cast(int, result.total_records) if result.error_count else 0,
                row_count_explanation="The whole revision awaits confirmation."
                if result.error_count == 0
                else "Blocking errors reject the whole revision for confirmation.",
                error_count=result.error_count,
                warning_count=result.warning_count,
                confirmation_blocked=result.error_count > 0,
                issues=[
                    ValidationIssue(
                        id=item.id,
                        code=item.code,
                        severity=cast(Literal["error", "warning"], item.severity),
                        message=item.message,
                        canonical_field=item.canonical_field,
                        source_column_ordinal=item.source_column_ordinal,
                        source_record_index=item.source_record_index,
                        related_record_index=item.related_record_index,
                    )
                    for item in persisted_issues
                ],
            )
        # A large issue set must fail explicitly, never silently omit blocking issues.
        if len(detail.model_dump_json().encode()) > self.settings.source_csv_max_bytes:
            raise ReviewResponseTooLarge
        return detail
