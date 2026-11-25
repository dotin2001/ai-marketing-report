"""Atomically confirm a reviewed CSV and commit its normalized dataset."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.source_schemas import ColumnMapping, ConfirmedImportDetail, ConfirmImportRequest
from app.core.config import Settings
from app.db.models import (
    CanonicalDataset,
    ConfirmedImport,
    DatasetCurrency,
    ImportColumnMapping,
    ImportConfiguration,
    ImportConfigurationRevision,
    ImportValidation,
    ImportValidationIssue,
    MetricResultSet,
    Report,
)
from app.db.repositories import (
    ConcurrencyConflict,
    confirm_import_validation,
    finalize_idempotency,
    get_import_configuration,
    get_import_validation,
    get_report,
    get_source,
    resolve_idempotency,
)
from app.db.session import transaction
from app.domain.assets import AssetServices, ResourceNotFound
from app.domain.datasets import CanonicalRowInput, commit_confirmed_dataset
from app.domain.metrics import ensure_current_metrics
from app.domain.reports import validate_idempotency_key
from app.processing.csv_import import (
    CanonicalRowCandidate,
    Issue,
    canonical_data_identity,
    process_csv,
)
from app.processing.normalization import POLICY_VERSION
from app.processing.source_envelope import parse_csv


class BlockedImportValidation(ValueError):
    """The selected validation contains blocking errors."""


class WarningAcknowledgementRequired(ValueError):
    """The exact warning set was not acknowledged."""


class StaleImportInput(ConcurrencyConflict):
    """The reviewed source, configuration, period, or issue result changed."""


@dataclass(frozen=True)
class _Captured:
    checksum: bytes
    configuration_id: UUID
    revision: int
    policy: str
    date_format: str | None
    period_start: date
    period_end: date
    period_revision: int
    total_records: int
    mappings: tuple[tuple[int, str], ...]
    issue_signature: tuple[tuple[object, ...], ...]
    warning_ids: frozenset[UUID]


def _issue_signature(
    issues: list[ImportValidationIssue] | tuple[Issue, ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            item.code,
            item.severity,
            item.message,
            item.canonical_field,
            item.source_column_ordinal,
            item.source_record_index,
            item.related_record_index,
        )
        for item in issues
    )


def _fingerprint(source_id: UUID, command: ConfirmImportRequest) -> bytes:
    payload = {
        "source_id": str(source_id),
        "validation_id": str(command.validation_id),
        "expected_revision": command.expected_revision,
        "acknowledged_warning_ids": sorted(str(item) for item in command.acknowledged_warning_ids),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).digest()


class ImportConfirmationServices:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.sessions = sessions
        self.settings = settings

    async def _authorize_pair(
        self, session: AsyncSession, owner_id: UUID, report_id: UUID, source_id: UUID
    ) -> Report:
        report = await get_report(session, owner_id=owner_id, report_id=report_id)
        source = await get_source(
            session, owner_id=owner_id, report_id=report_id, source_id=source_id
        )
        if report is None or source is None or source.source_type != "csv":
            raise ResourceNotFound
        return report

    async def _capture(
        self,
        session: AsyncSession,
        owner_id: UUID,
        report_id: UUID,
        source_id: UUID,
        command: ConfirmImportRequest,
    ) -> _Captured:
        report = await self._authorize_pair(session, owner_id, report_id, source_id)
        if report.current_source_id != source_id:
            raise StaleImportInput("source is no longer current")
        source = await get_source(
            session, owner_id=owner_id, report_id=report_id, source_id=source_id
        )
        assert source is not None
        config = await get_import_configuration(
            session, owner_id=owner_id, report_id=report_id, source_id=source_id
        )
        loaded = await get_import_validation(
            session, owner_id=owner_id, report_id=report_id, validation_id=command.validation_id
        )
        if config is None or loaded is None or config.current_revision != command.expected_revision:
            raise StaleImportInput("mapping revision changed")
        validation, issues = loaded
        if (
            validation.configuration_id != config.id
            or validation.revision != command.expected_revision
        ):
            raise StaleImportInput("validation revision changed")
        revision = await session.scalar(
            select(ImportConfigurationRevision).where(
                ImportConfigurationRevision.configuration_id == config.id,
                ImportConfigurationRevision.revision == command.expected_revision,
                ImportConfigurationRevision.owner_id == owner_id,
                ImportConfigurationRevision.report_id == report_id,
            )
        )
        if revision is None or revision.normalization_policy_version != POLICY_VERSION:
            raise StaleImportInput("normalization policy changed")
        if (
            validation.source_checksum != source.checksum_sha256
            or validation.period_start != report.period_start
            or validation.period_end != report.period_end
            or validation.period_revision != report.period_revision
            or validation.total_records is None
        ):
            raise StaleImportInput("review input changed")
        if validation.error_count != sum(
            item.severity == "error" for item in issues
        ) or validation.warning_count != sum(item.severity == "warning" for item in issues):
            raise StaleImportInput("validation summary changed")
        if validation.error_count:
            raise BlockedImportValidation
        warning_ids = frozenset(item.id for item in issues if item.severity == "warning")
        acknowledged = command.acknowledged_warning_ids
        if len(acknowledged) != len(set(acknowledged)) or set(acknowledged) != warning_ids:
            raise WarningAcknowledgementRequired
        mappings = tuple(
            (row.source_column_ordinal, row.canonical_field)
            for row in (
                await session.scalars(
                    select(ImportColumnMapping)
                    .where(
                        ImportColumnMapping.configuration_id == config.id,
                        ImportColumnMapping.revision == command.expected_revision,
                        ImportColumnMapping.owner_id == owner_id,
                        ImportColumnMapping.report_id == report_id,
                    )
                    .order_by(ImportColumnMapping.source_column_ordinal)
                )
            ).all()
        )
        return _Captured(
            source.checksum_sha256,
            config.id,
            command.expected_revision,
            revision.normalization_policy_version,
            revision.date_format,
            report.period_start,
            report.period_end,
            report.period_revision,
            validation.total_records,
            mappings,
            _issue_signature(issues),
            warning_ids,
        )

    async def _detail(
        self, session: AsyncSession, owner_id: UUID, report_id: UUID, confirmation_id: UUID
    ) -> ConfirmedImportDetail:
        confirmation = await session.scalar(
            select(ConfirmedImport).where(
                ConfirmedImport.id == confirmation_id,
                ConfirmedImport.owner_id == owner_id,
                ConfirmedImport.report_id == report_id,
            )
        )
        if confirmation is None:
            raise StaleImportInput("confirmation result unavailable")
        dataset = await session.scalar(
            select(CanonicalDataset).where(
                CanonicalDataset.confirmation_id == confirmation.id,
                CanonicalDataset.owner_id == owner_id,
                CanonicalDataset.report_id == report_id,
            )
        )
        validation = await session.scalar(
            select(ImportValidation).where(
                ImportValidation.id == confirmation.validation_id,
                ImportValidation.owner_id == owner_id,
                ImportValidation.report_id == report_id,
            )
        )
        revision = await session.scalar(
            select(ImportConfigurationRevision).where(
                ImportConfigurationRevision.configuration_id == confirmation.configuration_id,
                ImportConfigurationRevision.revision == confirmation.revision,
                ImportConfigurationRevision.owner_id == owner_id,
                ImportConfigurationRevision.report_id == report_id,
            )
        )
        configuration = await session.scalar(
            select(ImportConfiguration).where(
                ImportConfiguration.id == confirmation.configuration_id,
                ImportConfiguration.owner_id == owner_id,
                ImportConfiguration.report_id == report_id,
            )
        )
        if (
            dataset is None
            or validation is None
            or revision is None
            or configuration is None
            or validation.source_checksum is None
            or validation.period_revision is None
        ):
            raise StaleImportInput("confirmation provenance unavailable")
        currencies = list(
            (
                await session.scalars(
                    select(DatasetCurrency.currency)
                    .where(
                        DatasetCurrency.dataset_id == dataset.id,
                        DatasetCurrency.owner_id == owner_id,
                        DatasetCurrency.report_id == report_id,
                    )
                    .order_by(DatasetCurrency.currency)
                )
            ).all()
        )
        mappings = [
            ColumnMapping.model_validate(
                {
                    "source_column_ordinal": row.source_column_ordinal,
                    "canonical_field": row.canonical_field,
                }
            )
            for row in (
                await session.scalars(
                    select(ImportColumnMapping)
                    .where(
                        ImportColumnMapping.configuration_id == confirmation.configuration_id,
                        ImportColumnMapping.revision == confirmation.revision,
                        ImportColumnMapping.owner_id == owner_id,
                        ImportColumnMapping.report_id == report_id,
                    )
                    .order_by(ImportColumnMapping.source_column_ordinal)
                )
            ).all()
        ]
        metric_set = await session.scalar(
            select(MetricResultSet).where(
                MetricResultSet.dataset_id == dataset.id,
                MetricResultSet.owner_id == owner_id,
                MetricResultSet.report_id == report_id,
                MetricResultSet.calculation_version == "kpi-v1",
            )
        )
        return ConfirmedImportDetail(
            id=confirmation.id,
            report_id=report_id,
            source_id=configuration.source_id,
            validation_id=confirmation.validation_id,
            configuration_id=confirmation.configuration_id,
            revision=confirmation.revision,
            confirmed_by=confirmation.confirmed_by,
            dataset_id=dataset.id,
            canonical_data_identity=dataset.canonical_data_identity.hex(),
            source_checksum_sha256=validation.source_checksum.hex(),
            normalization_policy_version=revision.normalization_policy_version,
            period_start=confirmation.period_start,
            period_end=confirmation.period_end,
            period_revision=validation.period_revision,
            row_count=dataset.row_count,
            accepted_row_count=dataset.row_count,
            rejected_row_count=0,
            row_count_explanation="All source records were accepted, including warned duplicates.",
            metric_result_set_id=metric_set.id if metric_set else None,
            currencies=currencies,
            mappings=mappings,
        )

    async def confirm(
        self,
        owner_id: UUID,
        report_id: UUID,
        source_id: UUID,
        command: ConfirmImportRequest,
        key: str,
        assets: AssetServices,
    ) -> tuple[ConfirmedImportDetail, bool]:
        validate_idempotency_key(key)
        fingerprint = _fingerprint(source_id, command)
        async with transaction(self.sessions) as session:
            await self._authorize_pair(session, owner_id, report_id, source_id)
            idempotency = await resolve_idempotency(
                session,
                principal_id=owner_id,
                operation="confirm-import",
                scope_kind="report",
                scope_id=report_id,
                raw_key=key,
                command_fingerprint=fingerprint,
            )
            if idempotency.result_id is not None:
                return await self._detail(session, owner_id, report_id, idempotency.result_id), True
            captured = await self._capture(session, owner_id, report_id, source_id, command)
        verified = await assets.retrieve_csv(
            owner_id=owner_id, report_id=report_id, source_id=source_id
        )
        try:
            original = verified.file.read()
        finally:
            verified.close()
        envelope = parse_csv(
            original,
            max_bytes=self.settings.source_csv_max_bytes,
            max_records=self.settings.source_csv_max_records,
        )
        result = process_csv(
            envelope,
            list(captured.mappings),
            date_format=captured.date_format,
            period_start=captured.period_start,
            period_end=captured.period_end,
        )
        if (
            len(envelope.records) != captured.total_records
            or len(result.rows) != captured.total_records
            or _issue_signature(result.issues) != captured.issue_signature
            or any(item.severity == "error" for item in result.issues)
        ):
            raise StaleImportInput("validated rows no longer match")
        identity = canonical_data_identity(
            source_id=source_id,
            source_checksum=captured.checksum,
            configuration_id=captured.configuration_id,
            revision=captured.revision,
            normalization_policy_version=captured.policy,
            date_format=captured.date_format,
            period_start=captured.period_start,
            period_end=captured.period_end,
            period_revision=captured.period_revision,
            mappings=list(captured.mappings),
            rows=result.rows,
        )
        rows = [_to_input(row) for row in result.rows]
        async with transaction(self.sessions) as session:
            idempotency = await resolve_idempotency(
                session,
                principal_id=owner_id,
                operation="confirm-import",
                scope_kind="report",
                scope_id=report_id,
                raw_key=key,
                command_fingerprint=fingerprint,
            )
            if idempotency.result_id is not None:
                return await self._detail(session, owner_id, report_id, idempotency.result_id), True
            report = await session.scalar(
                select(Report)
                .where(Report.id == report_id, Report.owner_id == owner_id)
                .with_for_update()
            )
            if report is None:
                raise ResourceNotFound
            configuration = await session.scalar(
                select(ImportConfiguration)
                .where(
                    ImportConfiguration.id == captured.configuration_id,
                    ImportConfiguration.owner_id == owner_id,
                    ImportConfiguration.report_id == report_id,
                )
                .with_for_update()
            )
            if configuration is None or report.current_source_id != source_id:
                raise StaleImportInput("review input changed")
            current = await self._capture(session, owner_id, report_id, source_id, command)
            if current != captured:
                raise StaleImportInput("review input changed")
            existing = await session.scalar(
                select(ConfirmedImport).where(
                    ConfirmedImport.validation_id == command.validation_id,
                    ConfirmedImport.owner_id == owner_id,
                    ConfirmedImport.report_id == report_id,
                )
            )
            if existing is not None:
                if existing.canonical_data_identity != identity:
                    raise StaleImportInput("canonical identity changed")
                confirmation = existing
            else:
                confirmation = await confirm_import_validation(
                    session,
                    owner_id=owner_id,
                    report_id=report_id,
                    configuration_id=captured.configuration_id,
                    revision=captured.revision,
                    validation_id=command.validation_id,
                    confirmed_by=owner_id,
                    acknowledged_warning_ids=command.acknowledged_warning_ids,
                    canonical_data_identity=identity,
                    row_count=len(rows),
                    period_start=captured.period_start,
                    period_end=captured.period_end,
                )
            dataset = await commit_confirmed_dataset(
                session,
                owner_id=owner_id,
                report_id=report_id,
                confirmation_id=confirmation.id,
                rows=rows,
            )
            await ensure_current_metrics(
                session, owner_id=owner_id, report_id=report_id, dataset_id=dataset.id
            )
            await finalize_idempotency(
                session,
                record=idempotency,
                result_type="confirmed_import",
                result_id=confirmation.id,
                success_status=200,
            )
            return await self._detail(
                session, owner_id, report_id, confirmation.id
            ), existing is not None


def _to_input(row: CanonicalRowCandidate) -> CanonicalRowInput:
    return CanonicalRowInput(
        source_record_index=row.source_record_index,
        row_date=row.row_date,
        campaign_name=row.campaign_name,
        currency=row.currency,
        impressions=row.impressions,
        clicks=row.clicks,
        spend=row.spend,
        leads=row.leads,
    )
