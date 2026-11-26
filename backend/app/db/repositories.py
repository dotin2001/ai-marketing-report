"""Narrow owner-scoped persistence operations for reporting aggregates."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AnalysisItemClaimReference,
    AnalysisItemMetricReference,
    AnalysisJob,
    AnalysisJobAttempt,
    AnalysisResult,
    AnalysisResultItem,
    CanonicalDataset,
    CanonicalRow,
    ConfirmedImport,
    ConfirmedImportWarningAcknowledgement,
    DatasetCurrency,
    DraftChart,
    DraftChartMetricReference,
    DraftClaim,
    DraftLimitation,
    DraftNarrativeItem,
    DraftObjective,
    FileAsset,
    IdempotencyRecord,
    ImportColumnMapping,
    ImportConfiguration,
    ImportConfigurationRevision,
    ImportValidation,
    ImportValidationIssue,
    MetricResult,
    MetricResultCurrency,
    MetricResultInput,
    MetricResultSet,
    PdfExport,
    PdfExportAttempt,
    Report,
    ReportDraft,
    ReportSource,
    ReportVersion,
    SourceReviewConfirmation,
)
from app.db.snapshots import (
    ChartSnapshot,
    ReportVersionSnapshot,
    ReportVersionSnapshotV2,
    parse_report_version_snapshot,
)


class ConcurrencyConflict(RuntimeError):
    """The observed mutable revision/state no longer matches."""


class IdempotencyConflict(RuntimeError):
    """A scoped digest was reused for a different semantic command."""


class JobNotRetryable(RuntimeError):
    """The logical job has no eligible attempt remaining."""


ANALYSIS_MAX_TOTAL_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class SourceAssetAggregate:
    source: ReportSource
    asset: FileAsset


@dataclass(frozen=True, slots=True)
class PdfAssetAggregate:
    export: PdfExport
    version: ReportVersion
    asset: FileAsset | None


def _affected(result: object) -> int:
    """Read DML rowcount without widening repository result types."""

    return int(getattr(result, "rowcount", 0))


async def create_report(
    session: AsyncSession,
    *,
    owner_id: UUID,
    name: str,
    period_start: date,
    period_end: date,
    objectives: Sequence[str],
) -> tuple[Report, ReportDraft]:
    if not objectives or any(not objective.strip() for objective in objectives):
        raise ValueError("at least one non-blank objective is required")
    report = Report(
        owner_id=owner_id,
        name=name.strip(),
        period_start=period_start,
        period_end=period_end,
    )
    session.add(report)
    await session.flush()
    draft = ReportDraft(owner_id=owner_id, report_id=report.id, revision=1, is_active=True)
    session.add(draft)
    await session.flush()
    session.add_all(
        DraftObjective(
            owner_id=owner_id,
            report_id=report.id,
            draft_id=draft.id,
            ordinal=ordinal,
            content=content.strip(),
        )
        for ordinal, content in enumerate(objectives, start=1)
    )
    await session.flush()
    return report, draft


async def get_report(session: AsyncSession, *, owner_id: UUID, report_id: UUID) -> Report | None:
    return await session.scalar(
        select(Report).where(Report.owner_id == owner_id, Report.id == report_id)
    )


async def save_draft_objectives(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    draft_id: UUID,
    expected_revision: int,
    objectives: Sequence[str],
) -> int:
    if not objectives or any(not objective.strip() for objective in objectives):
        raise ValueError("at least one non-blank objective is required")
    result = await session.execute(
        update(ReportDraft)
        .where(
            ReportDraft.owner_id == owner_id,
            ReportDraft.report_id == report_id,
            ReportDraft.id == draft_id,
            ReportDraft.is_active.is_(True),
            ReportDraft.revision == expected_revision,
        )
        .values(
            revision=expected_revision + 1,
            objectives_revision=expected_revision + 1,
            updated_at=func.current_timestamp(),
        )
    )
    if _affected(result) != 1:
        raise ConcurrencyConflict("draft revision is stale")
    await session.execute(
        delete(DraftObjective).where(
            DraftObjective.owner_id == owner_id,
            DraftObjective.report_id == report_id,
            DraftObjective.draft_id == draft_id,
        )
    )
    session.add_all(
        DraftObjective(
            owner_id=owner_id,
            report_id=report_id,
            draft_id=draft_id,
            ordinal=ordinal,
            content=content.strip(),
        )
        for ordinal, content in enumerate(objectives, start=1)
    )
    return expected_revision + 1


async def save_draft_charts(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    draft_id: UUID,
    expected_revision: int,
    charts: Sequence[ChartSnapshot | dict[str, object]],
) -> int:
    if len(charts) > 16:
        raise ValueError("at most 16 charts are allowed")
    validated = tuple(ChartSnapshot.model_validate(chart) for chart in charts)
    report = await session.scalar(
        select(Report).where(Report.id == report_id, Report.owner_id == owner_id).with_for_update()
    )
    if report is None:
        raise ConcurrencyConflict("report is unavailable")
    metric_ids = {metric_id for chart in validated for metric_id in chart.metric_result_ids}
    if metric_ids:
        if report.current_metric_result_set_id is None:
            raise ValueError("charts require a current metric result set")
        found = set(
            await session.scalars(
                select(MetricResult.id).where(
                    MetricResult.id.in_(metric_ids),
                    MetricResult.report_id == report_id,
                    MetricResult.owner_id == owner_id,
                    MetricResult.result_set_id == report.current_metric_result_set_id,
                )
            )
        )
        if found != metric_ids:
            raise ValueError("chart metric reference is not current for this report")
    changed = await session.execute(
        update(ReportDraft)
        .where(
            ReportDraft.id == draft_id,
            ReportDraft.report_id == report_id,
            ReportDraft.owner_id == owner_id,
            ReportDraft.is_active.is_(True),
            ReportDraft.revision == expected_revision,
        )
        .values(revision=expected_revision + 1, updated_at=func.current_timestamp())
    )
    if _affected(changed) != 1:
        raise ConcurrencyConflict("draft revision is stale")
    old_ids = list(
        await session.scalars(
            select(DraftChart.id).where(
                DraftChart.draft_id == draft_id,
                DraftChart.report_id == report_id,
                DraftChart.owner_id == owner_id,
            )
        )
    )
    if old_ids:
        await session.execute(
            delete(DraftChartMetricReference).where(DraftChartMetricReference.chart_id.in_(old_ids))
        )
        await session.execute(delete(DraftChart).where(DraftChart.id.in_(old_ids)))
    for ordinal, declaration in enumerate(validated, start=1):
        chart = DraftChart(
            owner_id=owner_id,
            report_id=report_id,
            draft_id=draft_id,
            ordinal=ordinal,
            chart_type=declaration.chart_type,
            title=declaration.title,
            x_label=declaration.x_label,
            y_label=declaration.y_label,
            scope=declaration.scope,
        )
        session.add(chart)
        await session.flush()
        session.add_all(
            DraftChartMetricReference(
                chart_id=chart.id,
                ordinal=metric_ordinal,
                metric_result_id=metric_id,
                owner_id=owner_id,
                report_id=report_id,
                draft_id=draft_id,
            )
            for metric_ordinal, metric_id in enumerate(declaration.metric_result_ids, start=1)
        )
    await session.flush()
    return expected_revision + 1


async def activate_restored_draft(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    objectives: Sequence[str],
) -> ReportDraft:
    if not objectives or any(not objective.strip() for objective in objectives):
        raise ValueError("at least one non-blank objective is required")
    report = await session.scalar(
        select(Report).where(Report.owner_id == owner_id, Report.id == report_id).with_for_update()
    )
    if report is None:
        raise ConcurrencyConflict("report is unavailable")
    await session.execute(
        update(ReportDraft)
        .where(
            ReportDraft.owner_id == owner_id,
            ReportDraft.report_id == report_id,
            ReportDraft.is_active.is_(True),
        )
        .values(is_active=False, updated_at=func.current_timestamp())
    )
    draft = ReportDraft(owner_id=owner_id, report_id=report_id, revision=1, is_active=True)
    session.add(draft)
    await session.flush()
    session.add_all(
        DraftObjective(
            owner_id=owner_id,
            report_id=report_id,
            draft_id=draft.id,
            ordinal=index,
            content=value.strip(),
        )
        for index, value in enumerate(objectives, start=1)
    )
    return draft


async def attach_source(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    source: ReportSource,
    asset: FileAsset | None = None,
) -> ReportSource:
    if asset is not None:
        if asset.owner_id != owner_id or asset.report_id != report_id:
            raise ConcurrencyConflict("source asset aggregate is unavailable")
        session.add(asset)
        await session.flush()
        source.asset_id = asset.id
        source.asset_purpose = asset.purpose
    session.add(source)
    await session.flush()
    changed = await session.execute(
        update(Report)
        .where(Report.owner_id == owner_id, Report.id == report_id)
        .values(
            current_source_id=source.id,
            current_dataset_id=None,
            current_metric_result_set_id=None,
            current_analysis_result_id=None,
        )
    )
    if _affected(changed) != 1:
        raise ConcurrencyConflict("report is unavailable")
    return source


async def get_source(
    session: AsyncSession, *, owner_id: UUID, report_id: UUID, source_id: UUID
) -> ReportSource | None:
    return await session.scalar(
        select(ReportSource).where(
            ReportSource.owner_id == owner_id,
            ReportSource.report_id == report_id,
            ReportSource.id == source_id,
        )
    )


async def get_source_asset(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    source_id: UUID,
) -> SourceAssetAggregate | None:
    row = (
        await session.execute(
            select(ReportSource, FileAsset)
            .join(
                FileAsset,
                (FileAsset.id == ReportSource.asset_id)
                & (FileAsset.owner_id == ReportSource.owner_id)
                & (FileAsset.report_id == ReportSource.report_id),
            )
            .where(
                ReportSource.owner_id == owner_id,
                ReportSource.report_id == report_id,
                ReportSource.id == source_id,
                ReportSource.source_type == "csv",
                FileAsset.purpose == "source_csv",
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return SourceAssetAggregate(source=row[0], asset=row[1])


def file_asset_metadata_matches(left: FileAsset, right: FileAsset) -> bool:
    fields = (
        "owner_id",
        "report_id",
        "purpose",
        "environment",
        "bucket",
        "object_key",
        "safe_filename",
        "content_type",
        "byte_size",
        "checksum_sha256",
        "version_id",
        "export_id",
    )
    return all(getattr(left, field) == getattr(right, field) for field in fields)


async def insert_or_load_csv_binding(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    source: ReportSource,
    asset: FileAsset,
) -> SourceAssetAggregate:
    existing = await get_source_asset(
        session,
        owner_id=owner_id,
        report_id=report_id,
        source_id=source.id,
    )
    if existing is not None:
        source_matches = (
            existing.source.checksum_sha256 == source.checksum_sha256
            and existing.source.byte_size == source.byte_size
            and existing.source.media_type == source.media_type
            and existing.source.encoding == source.encoding
            and existing.source.original_filename == source.original_filename
            and existing.source.display_filename == source.display_filename
        )
        if not source_matches or not file_asset_metadata_matches(existing.asset, asset):
            raise ConcurrencyConflict("source asset binding conflicts with existing metadata")
        return existing
    if source.owner_id != owner_id or source.report_id != report_id:
        raise ConcurrencyConflict("source asset aggregate is unavailable")
    await attach_source(
        session,
        owner_id=owner_id,
        report_id=report_id,
        source=source,
        asset=asset,
    )
    return SourceAssetAggregate(source=source, asset=asset)


async def confirm_source_review(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    source_id: UUID,
    source_checksum: bytes,
    confirmed_by: UUID,
) -> SourceReviewConfirmation:
    if confirmed_by != owner_id:
        raise ConcurrencyConflict("source review owner is unavailable")
    source = await session.scalar(
        select(ReportSource)
        .where(
            ReportSource.owner_id == owner_id,
            ReportSource.report_id == report_id,
            ReportSource.id == source_id,
            ReportSource.source_type == "text",
        )
        .with_for_update()
    )
    if source is None or source.checksum_sha256 != source_checksum:
        raise ConcurrencyConflict("source review revision is stale")
    report = await session.scalar(
        select(Report)
        .where(
            Report.id == report_id,
            Report.owner_id == owner_id,
            Report.current_source_id == source_id,
        )
        .with_for_update()
    )
    if report is None:
        raise ConcurrencyConflict("source review revision is stale")
    confirmation = SourceReviewConfirmation(
        owner_id=owner_id,
        report_id=report_id,
        source_id=source_id,
        source_checksum=source_checksum,
        period_start=report.period_start,
        period_end=report.period_end,
        period_revision=report.period_revision,
        confirmed_by=confirmed_by,
    )
    session.add(confirmation)
    await session.flush()
    return confirmation


async def append_import_revision(
    session: AsyncSession,
    *,
    configuration_id: UUID,
    owner_id: UUID,
    report_id: UUID,
    expected_revision: int,
    normalization_policy_version: str,
    mappings: Sequence[tuple[int, str]],
    date_format: str | None = None,
) -> int:
    _check_mapping_structure(mappings)
    next_revision = expected_revision + 1
    changed = await session.execute(
        update(ImportConfiguration)
        .where(
            ImportConfiguration.id == configuration_id,
            ImportConfiguration.owner_id == owner_id,
            ImportConfiguration.report_id == report_id,
            ImportConfiguration.current_revision == expected_revision,
        )
        .values(current_revision=next_revision, updated_at=func.current_timestamp())
    )
    if _affected(changed) != 1:
        raise ConcurrencyConflict("import configuration revision is stale")
    session.add(
        ImportConfigurationRevision(
            owner_id=owner_id,
            report_id=report_id,
            configuration_id=configuration_id,
            revision=next_revision,
            normalization_policy_version=normalization_policy_version,
            date_format=date_format,
        )
    )
    await session.flush()
    session.add_all(
        ImportColumnMapping(
            owner_id=owner_id,
            report_id=report_id,
            configuration_id=configuration_id,
            revision=next_revision,
            source_column_ordinal=ordinal,
            canonical_field=field,
        )
        for ordinal, field in mappings
    )
    return next_revision


def _check_mapping_structure(mappings: Sequence[tuple[int, str]]) -> None:
    allowed = {"date", "campaign_name", "currency", "impressions", "clicks", "spend", "leads"}
    ordinals = [ordinal for ordinal, _ in mappings]
    fields = [field for _, field in mappings]
    if any(ordinal < 0 for ordinal in ordinals) or any(field not in allowed for field in fields):
        raise ValueError("invalid mapping")
    if len(set(ordinals)) != len(ordinals) or len(set(fields)) != len(fields):
        raise ValueError("duplicate mapping")


async def create_import_configuration(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    source_id: UUID,
    normalization_policy_version: str,
    mappings: Sequence[tuple[int, str]],
    date_format: str | None = None,
) -> ImportConfiguration:
    _check_mapping_structure(mappings)
    configuration = ImportConfiguration(
        owner_id=owner_id,
        report_id=report_id,
        source_id=source_id,
        source_type="csv",
        current_revision=1,
    )
    session.add(configuration)
    await session.flush()
    session.add(
        ImportConfigurationRevision(
            owner_id=owner_id,
            report_id=report_id,
            configuration_id=configuration.id,
            revision=1,
            normalization_policy_version=normalization_policy_version,
            date_format=date_format,
        )
    )
    await session.flush()
    session.add_all(
        ImportColumnMapping(
            owner_id=owner_id,
            report_id=report_id,
            configuration_id=configuration.id,
            revision=1,
            source_column_ordinal=ordinal,
            canonical_field=field,
        )
        for ordinal, field in mappings
    )
    await session.flush()
    return configuration


async def get_import_configuration(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    source_id: UUID,
) -> ImportConfiguration | None:
    return await session.scalar(
        select(ImportConfiguration).where(
            ImportConfiguration.owner_id == owner_id,
            ImportConfiguration.report_id == report_id,
            ImportConfiguration.source_id == source_id,
        )
    )


async def persist_import_validation(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    configuration_id: UUID,
    revision: int,
    source_checksum: bytes,
    period_start: date,
    period_end: date,
    period_revision: int,
    total_records: int,
    issues: Sequence[dict[str, object]],
) -> ImportValidation:
    result = ImportValidation(
        owner_id=owner_id,
        report_id=report_id,
        configuration_id=configuration_id,
        revision=revision,
        source_checksum=source_checksum,
        period_start=period_start,
        period_end=period_end,
        period_revision=period_revision,
        total_records=total_records,
        error_count=sum(issue["severity"] == "error" for issue in issues),
        warning_count=sum(issue["severity"] == "warning" for issue in issues),
    )
    session.add(result)
    await session.flush()
    session.add_all(
        ImportValidationIssue(
            owner_id=owner_id, report_id=report_id, validation_id=result.id, ordinal=index, **issue
        )
        for index, issue in enumerate(issues, 1)
    )
    await session.flush()
    return result


async def get_import_validation(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    validation_id: UUID,
) -> tuple[ImportValidation, list[ImportValidationIssue]] | None:
    result = await session.scalar(
        select(ImportValidation).where(
            ImportValidation.id == validation_id,
            ImportValidation.owner_id == owner_id,
            ImportValidation.report_id == report_id,
        )
    )
    if result is None:
        return None
    issues = list(
        (
            await session.scalars(
                select(ImportValidationIssue)
                .where(
                    ImportValidationIssue.validation_id == validation_id,
                    ImportValidationIssue.owner_id == owner_id,
                    ImportValidationIssue.report_id == report_id,
                )
                .order_by(ImportValidationIssue.ordinal)
            )
        ).all()
    )
    return result, issues


async def confirm_import_validation(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    configuration_id: UUID,
    revision: int,
    validation_id: UUID,
    confirmed_by: UUID,
    acknowledged_warning_ids: Sequence[UUID],
    canonical_data_identity: bytes,
    row_count: int,
    period_start: date,
    period_end: date,
) -> ConfirmedImport:
    if confirmed_by != owner_id:
        raise ConcurrencyConflict("import confirmation owner is unavailable")
    report = await session.scalar(
        select(Report)
        .where(
            Report.id == report_id,
            Report.owner_id == owner_id,
        )
        .with_for_update()
    )
    configuration = await session.scalar(
        select(ImportConfiguration)
        .where(
            ImportConfiguration.id == configuration_id,
            ImportConfiguration.owner_id == owner_id,
            ImportConfiguration.report_id == report_id,
            ImportConfiguration.current_revision == revision,
        )
        .with_for_update()
    )
    validation = await session.scalar(
        select(ImportValidation).where(
            ImportValidation.id == validation_id,
            ImportValidation.owner_id == owner_id,
            ImportValidation.report_id == report_id,
            ImportValidation.configuration_id == configuration_id,
            ImportValidation.revision == revision,
        )
    )
    if configuration is None or validation is None or report is None:
        raise ConcurrencyConflict("import validation revision is stale")
    source = await get_source(
        session, owner_id=owner_id, report_id=report_id, source_id=configuration.source_id
    )
    if (
        report is None
        or report.current_source_id != configuration.source_id
        or source is None
        or validation.source_checksum is None
        or validation.source_checksum != source.checksum_sha256
        or validation.period_start != report.period_start
        or validation.period_end != report.period_end
        or validation.period_revision != report.period_revision
        or period_start != report.period_start
        or period_end != report.period_end
    ):
        raise ConcurrencyConflict("import validation input is stale")

    issues = (
        await session.scalars(
            select(ImportValidationIssue)
            .where(
                ImportValidationIssue.owner_id == owner_id,
                ImportValidationIssue.report_id == report_id,
                ImportValidationIssue.validation_id == validation_id,
            )
            .order_by(ImportValidationIssue.ordinal)
        )
    ).all()
    errors = [issue for issue in issues if issue.severity == "error"]
    warning_ids = {issue.id for issue in issues if issue.severity == "warning"}
    if validation.error_count != len(errors) or validation.warning_count != len(warning_ids):
        raise ValueError("validation issue summary is inconsistent")
    if errors:
        raise ValueError("validation contains blocking errors")
    acknowledged = list(acknowledged_warning_ids)
    if len(acknowledged) != len(set(acknowledged)) or set(acknowledged) != warning_ids:
        raise ValueError("warning acknowledgement set is incomplete")

    confirmation = ConfirmedImport(
        owner_id=owner_id,
        report_id=report_id,
        validation_id=validation_id,
        configuration_id=configuration_id,
        revision=revision,
        confirmed_by=confirmed_by,
        canonical_data_identity=canonical_data_identity,
        row_count=row_count,
        period_start=period_start,
        period_end=period_end,
    )
    session.add(confirmation)
    await session.flush()
    session.add_all(
        ConfirmedImportWarningAcknowledgement(
            confirmation_id=confirmation.id,
            issue_id=issue_id,
            owner_id=owner_id,
            report_id=report_id,
        )
        for issue_id in acknowledged
    )
    await session.flush()
    return confirmation


async def attach_dataset_and_metrics(
    session: AsyncSession,
    *,
    report: Report,
    dataset: CanonicalDataset,
    dataset_currencies: Sequence[DatasetCurrency],
    rows: Sequence[CanonicalRow],
    metric_set: MetricResultSet,
    metric_results: Sequence[MetricResult],
    metric_inputs: Sequence[MetricResultInput] = (),
    metric_currencies: Sequence[MetricResultCurrency] = (),
) -> None:
    if dataset.owner_id != report.owner_id or dataset.report_id != report.id:
        raise ValueError("dataset aggregate does not match report")
    if len(rows) != dataset.row_count:
        raise ValueError("dataset row count does not match rows")
    if not rows:
        raise ValueError("canonical dataset must contain rows")
    if any(
        row.row_date < dataset.period_start or row.row_date > dataset.period_end for row in rows
    ):
        raise ValueError("canonical row is outside the dataset period")
    record_indexes = [row.source_record_index for row in rows]
    if len(record_indexes) != len(set(record_indexes)):
        raise ValueError("canonical source record indexes are duplicated")
    represented_currencies = {currency.currency for currency in dataset_currencies}
    if not represented_currencies or represented_currencies != {row.currency for row in rows}:
        raise ValueError("dataset currency provenance does not match rows")
    if any(
        all(value is None for value in (row.impressions, row.clicks, row.spend, row.leads))
        for row in rows
    ):
        raise ValueError("canonical row must contain at least one measure")
    if not metric_results:
        raise ValueError("metric result set must contain results")
    if metric_set.owner_id != report.owner_id or metric_set.report_id != report.id:
        raise ValueError("metric aggregate does not match report")

    session.add(dataset)
    await session.flush()
    for currency in dataset_currencies:
        currency.dataset_id = dataset.id
        currency.owner_id = report.owner_id
        currency.report_id = report.id
    session.add_all(dataset_currencies)
    await session.flush()
    for row in rows:
        row.dataset_id = dataset.id
        row.owner_id = report.owner_id
        row.report_id = report.id
    session.add_all(rows)
    metric_set.dataset_id = dataset.id
    session.add(metric_set)
    await session.flush()
    for result in metric_results:
        result.result_set_id = metric_set.id
        result.owner_id = report.owner_id
        result.report_id = report.id
    session.add_all(metric_results)
    await session.flush()
    result_ids = {result.id for result in metric_results}
    if any(item.metric_result_id not in result_ids for item in metric_inputs) or any(
        item.metric_result_id not in result_ids for item in metric_currencies
    ):
        raise ValueError("metric provenance references an unknown result")
    session.add_all(metric_inputs)
    session.add_all(metric_currencies)
    await session.flush()
    report.current_dataset_id = dataset.id
    report.current_metric_result_set_id = metric_set.id
    report.current_analysis_result_id = None


async def claim_analysis_job(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    job_id: UUID,
    expected_attempt_count: int | None = None,
) -> bool:
    async with session.begin_nested():
        job = await session.scalar(
            select(AnalysisJob)
            .where(
                AnalysisJob.owner_id == owner_id,
                AnalysisJob.report_id == report_id,
                AnalysisJob.id == job_id,
            )
            .with_for_update()
        )
        if (
            job is None
            or job.state != "queued"
            or (expected_attempt_count is not None and job.attempt_count != expected_attempt_count)
        ):
            return False
        now = datetime.now(UTC)
        attempt_changed = await session.execute(
            update(AnalysisJobAttempt)
            .where(
                AnalysisJobAttempt.owner_id == owner_id,
                AnalysisJobAttempt.report_id == report_id,
                AnalysisJobAttempt.job_id == job_id,
                AnalysisJobAttempt.attempt_ordinal == job.attempt_count,
                AnalysisJobAttempt.state == "queued",
            )
            .values(state="running", started_at=now)
        )
        if _affected(attempt_changed) != 1:
            raise ConcurrencyConflict("analysis attempt state is stale")
        job.state = "running"
        job.updated_at = now
        await session.flush()
        return True


async def queued_analysis_attempts(
    session: AsyncSession, *, limit: int = 100
) -> list[tuple[UUID, UUID, UUID, int]]:
    if not 1 <= limit <= 500:
        raise ValueError("invalid recovery batch size")
    rows = await session.execute(
        select(
            AnalysisJob.owner_id, AnalysisJob.report_id, AnalysisJob.id, AnalysisJob.attempt_count
        )
        .join(
            AnalysisJobAttempt,
            (AnalysisJobAttempt.job_id == AnalysisJob.id)
            & (AnalysisJobAttempt.attempt_ordinal == AnalysisJob.attempt_count),
        )
        .where(AnalysisJob.state == "queued", AnalysisJobAttempt.state == "queued")
        .order_by(AnalysisJobAttempt.queued_at, AnalysisJob.id)
        .limit(limit)
    )
    return [(row[0], row[1], row[2], row[3]) for row in rows]


async def stale_running_analysis_attempts(
    session: AsyncSession, *, before: datetime, limit: int = 100
) -> list[tuple[UUID, UUID, UUID, int]]:
    if not 1 <= limit <= 500 or before.tzinfo is None:
        raise ValueError("invalid stale running scan")
    rows = await session.execute(
        select(
            AnalysisJob.owner_id, AnalysisJob.report_id, AnalysisJob.id, AnalysisJob.attempt_count
        )
        .join(
            AnalysisJobAttempt,
            (AnalysisJobAttempt.job_id == AnalysisJob.id)
            & (AnalysisJobAttempt.attempt_ordinal == AnalysisJob.attempt_count),
        )
        .where(
            AnalysisJob.state == "running",
            AnalysisJobAttempt.state == "running",
            AnalysisJobAttempt.started_at < before,
        )
        .order_by(AnalysisJobAttempt.started_at, AnalysisJob.id)
        .limit(limit)
    )
    return [(row[0], row[1], row[2], row[3]) for row in rows]


async def create_analysis_job(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    semantic_input_identity: bytes,
    dataset_id: UUID,
    metric_result_set_id: UUID,
    draft_id: UUID,
    draft_revision: int,
    objectives_revision: int,
    idempotency: IdempotencyRecord | None = None,
) -> AnalysisJob:
    if len(semantic_input_identity) != 32:
        raise ValueError("semantic input identity must be SHA-256")
    if idempotency is not None and idempotency.result_id is not None:
        if idempotency.result_type != "analysis_job":
            raise IdempotencyConflict("idempotency result type does not match analysis job")
        replay = await session.scalar(
            select(AnalysisJob).where(
                AnalysisJob.id == idempotency.result_id,
                AnalysisJob.owner_id == owner_id,
                AnalysisJob.report_id == report_id,
            )
        )
        if replay is None:
            raise IdempotencyConflict("idempotency result is unavailable")
        return replay

    report = await session.scalar(
        select(Report)
        .where(
            Report.owner_id == owner_id,
            Report.id == report_id,
            Report.current_dataset_id == dataset_id,
            Report.current_metric_result_set_id == metric_result_set_id,
        )
        .with_for_update()
    )
    draft = await session.scalar(
        select(ReportDraft).where(
            ReportDraft.owner_id == owner_id,
            ReportDraft.report_id == report_id,
            ReportDraft.id == draft_id,
            ReportDraft.is_active.is_(True),
            ReportDraft.revision == draft_revision,
        )
    )
    if report is None or draft is None or objectives_revision != draft.objectives_revision:
        raise ConcurrencyConflict("analysis input revision is stale")

    inserted = await session.scalar(
        pg_insert(AnalysisJob)
        .values(
            owner_id=owner_id,
            report_id=report_id,
            semantic_input_identity=semantic_input_identity,
            dataset_id=dataset_id,
            metric_result_set_id=metric_result_set_id,
            draft_id=draft_id,
            draft_revision=draft_revision,
            objectives_revision=objectives_revision,
            state="queued",
            attempt_count=1,
        )
        .on_conflict_do_nothing(
            index_elements=[AnalysisJob.report_id, AnalysisJob.semantic_input_identity]
        )
        .returning(AnalysisJob)
    )
    if inserted is None:
        inserted = await session.scalar(
            select(AnalysisJob).where(
                AnalysisJob.report_id == report_id,
                AnalysisJob.semantic_input_identity == semantic_input_identity,
            )
        )
        if inserted is None:
            raise ConcurrencyConflict("analysis job creation raced without a durable result")
    else:
        session.add(
            AnalysisJobAttempt(
                owner_id=owner_id,
                report_id=report_id,
                job_id=inserted.id,
                attempt_ordinal=1,
                state="queued",
                queued_at=datetime.now(UTC),
            )
        )
        await session.flush()
    if idempotency is not None:
        await finalize_idempotency(
            session,
            record=idempotency,
            result_type="analysis_job",
            result_id=inserted.id,
            success_status=202,
        )
    return inserted


async def finish_analysis_job(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    job_id: UUID,
    expected_attempt_count: int,
    result: AnalysisResult,
    items: Sequence[AnalysisResultItem],
    metric_references: Sequence[AnalysisItemMetricReference] = (),
    claim_references: Sequence[AnalysisItemClaimReference] = (),
) -> bool:
    async with session.begin_nested():
        job = await session.scalar(
            select(AnalysisJob)
            .where(
                AnalysisJob.owner_id == owner_id,
                AnalysisJob.report_id == report_id,
                AnalysisJob.id == job_id,
            )
            .with_for_update()
        )
        if job is None or job.state != "running" or job.attempt_count != expected_attempt_count:
            raise ConcurrencyConflict("analysis completion state is stale")
        metric_identity = await session.scalar(
            select(MetricResultSet.identity).where(
                MetricResultSet.id == job.metric_result_set_id,
                MetricResultSet.owner_id == owner_id,
                MetricResultSet.report_id == report_id,
            )
        )
        if (
            result.owner_id != owner_id
            or result.report_id != report_id
            or result.job_id != job_id
            or result.semantic_input_identity != job.semantic_input_identity
            or result.numeric_source_identity != metric_identity
        ):
            raise ValueError("analysis result provenance does not match the logical job")

        # Serialize attachment with edits to the active draft, then compare the
        # complete semantic identity while both aggregate rows are locked.
        report = await session.scalar(
            select(Report)
            .where(Report.owner_id == owner_id, Report.id == report_id)
            .with_for_update()
        )
        active_draft = await session.scalar(
            select(ReportDraft)
            .where(
                ReportDraft.owner_id == owner_id,
                ReportDraft.report_id == report_id,
                ReportDraft.is_active.is_(True),
            )
            .with_for_update()
        )
        fresh = False
        if report is not None and active_draft is not None:
            from app.domain.analysis_jobs import current_analysis_input

            try:
                _draft, _dataset, _metrics, identity = await current_analysis_input(
                    session, report, job.draft_revision, job.dataset_id, job.metric_result_set_id
                )
                fresh = identity == job.semantic_input_identity
            except ConcurrencyConflict:
                pass
        if not fresh:
            await fail_analysis_job(
                session,
                owner_id=owner_id,
                report_id=report_id,
                job_id=job_id,
                expected_attempt_count=expected_attempt_count,
                failure_code="stale_result",
                failure_message="Analysis input changed.",
                retryable=False,
            )
            return False

        session.add(result)
        await session.flush()
        for item in items:
            if item.owner_id != owner_id or item.report_id != report_id:
                raise ValueError("analysis result item aggregate does not match")
            item.result_id = result.id
        session.add_all(items)
        await session.flush()
        item_ids = {item.id for item in items}
        if any(ref.item_id not in item_ids for ref in metric_references) or any(
            ref.item_id not in item_ids for ref in claim_references
        ):
            raise ValueError("analysis reference points outside the result")
        session.add_all(metric_references)
        session.add_all(claim_references)
        await session.flush()

        now = datetime.now(UTC)
        attempt_changed = await session.execute(
            update(AnalysisJobAttempt)
            .where(
                AnalysisJobAttempt.owner_id == owner_id,
                AnalysisJobAttempt.report_id == report_id,
                AnalysisJobAttempt.job_id == job_id,
                AnalysisJobAttempt.attempt_ordinal == expected_attempt_count,
                AnalysisJobAttempt.state == "running",
            )
            .values(state="succeeded", finished_at=now)
        )
        if _affected(attempt_changed) != 1:
            raise ConcurrencyConflict("analysis attempt completion state is stale")
        job.state = "succeeded"
        job.current_result_id = result.id
        job.updated_at = now

        assert report is not None and active_draft is not None
        report.current_analysis_result_id = result.id
        active_draft.current_analysis_result_id = result.id
        active_draft.current_metric_result_set_id = job.metric_result_set_id
        await session.flush()
        return True


def _sanitized_failure(code: str, message: str) -> tuple[str, str]:
    normalized_code = code.strip()
    normalized_message = " ".join(message.split())
    if not re.fullmatch(r"[a-z0-9_]{1,64}", normalized_code):
        raise ValueError("failure code is not an approved sanitized identifier")
    if not normalized_message or len(normalized_message) > 500:
        raise ValueError("failure message is not a safe bounded value")
    return normalized_code, normalized_message


async def fail_analysis_job(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    job_id: UUID,
    expected_attempt_count: int,
    failure_code: str,
    failure_message: str,
    retryable: bool,
) -> None:
    safe_code, safe_message = _sanitized_failure(failure_code, failure_message)
    async with session.begin_nested():
        now = datetime.now(UTC)
        changed = await session.execute(
            update(AnalysisJob)
            .where(
                AnalysisJob.owner_id == owner_id,
                AnalysisJob.report_id == report_id,
                AnalysisJob.id == job_id,
                AnalysisJob.state == "running",
                AnalysisJob.attempt_count == expected_attempt_count,
            )
            .values(
                state="failed",
                failure_code=safe_code,
                failure_message=safe_message,
                failure_retryable=retryable,
                updated_at=now,
            )
        )
        attempt_changed = await session.execute(
            update(AnalysisJobAttempt)
            .where(
                AnalysisJobAttempt.owner_id == owner_id,
                AnalysisJobAttempt.report_id == report_id,
                AnalysisJobAttempt.job_id == job_id,
                AnalysisJobAttempt.attempt_ordinal == expected_attempt_count,
                AnalysisJobAttempt.state == "running",
            )
            .values(
                state="failed",
                finished_at=now,
                failure_code=safe_code,
                failure_message=safe_message,
                failure_retryable=retryable,
            )
        )
        if _affected(changed) != 1 or _affected(attempt_changed) != 1:
            raise ConcurrencyConflict("analysis failure state is stale")


async def retry_analysis_job(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    job_id: UUID,
    expected_attempt_count: int,
) -> int:
    async with session.begin_nested():
        job = await session.scalar(
            select(AnalysisJob)
            .where(
                AnalysisJob.owner_id == owner_id,
                AnalysisJob.report_id == report_id,
                AnalysisJob.id == job_id,
            )
            .with_for_update()
        )
        if job is None:
            raise ConcurrencyConflict("analysis retry state or input is stale")
        report = await session.scalar(
            select(Report).where(Report.owner_id == owner_id, Report.id == report_id)
        )
        draft = await session.scalar(
            select(ReportDraft).where(
                ReportDraft.owner_id == owner_id,
                ReportDraft.report_id == report_id,
                ReportDraft.id == job.draft_id,
                ReportDraft.is_active.is_(True),
            )
        )
        if (
            report is None
            or draft is None
            or job.attempt_count != expected_attempt_count
            or report.current_dataset_id != job.dataset_id
            or report.current_metric_result_set_id != job.metric_result_set_id
            or draft.objectives_revision != job.objectives_revision
            or draft.revision != job.draft_revision
        ):
            raise ConcurrencyConflict("analysis retry state or input is stale")
        if job.state != "failed":
            raise ConcurrencyConflict("analysis retry state or input is stale")
        if job.failure_retryable is not True or job.attempt_count >= ANALYSIS_MAX_TOTAL_ATTEMPTS:
            raise JobNotRetryable("analysis job is not retryable")
        next_ordinal = expected_attempt_count + 1
        job.state = "queued"
        job.attempt_count = next_ordinal
        job.failure_code = None
        job.failure_message = None
        job.failure_retryable = None
        session.add(
            AnalysisJobAttempt(
                owner_id=owner_id,
                report_id=report_id,
                job_id=job_id,
                attempt_ordinal=next_ordinal,
                state="queued",
                queued_at=datetime.now(UTC),
            )
        )
        await session.flush()
        return next_ordinal


async def resolve_idempotency(
    session: AsyncSession,
    *,
    principal_id: UUID,
    operation: str,
    scope_kind: str,
    scope_id: UUID,
    raw_key: str,
    command_fingerprint: bytes,
) -> IdempotencyRecord:
    digest = sha256(raw_key.encode()).digest()
    inserted_id = await session.scalar(
        pg_insert(IdempotencyRecord)
        .values(
            principal_id=principal_id,
            operation=operation,
            scope_kind=scope_kind,
            scope_id=scope_id,
            key_digest=digest,
            command_fingerprint=command_fingerprint,
        )
        .on_conflict_do_nothing(
            index_elements=[
                IdempotencyRecord.principal_id,
                IdempotencyRecord.operation,
                IdempotencyRecord.scope_kind,
                IdempotencyRecord.scope_id,
                IdempotencyRecord.key_digest,
            ]
        )
        .returning(IdempotencyRecord.id)
    )
    existing = await session.scalar(
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.principal_id == principal_id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.scope_kind == scope_kind,
            IdempotencyRecord.scope_id == scope_id,
            IdempotencyRecord.key_digest == digest,
        )
        .with_for_update()
    )
    if existing is None or (inserted_id is not None and existing.id != inserted_id):
        raise ConcurrencyConflict("idempotency record creation did not become durable")
    if existing.command_fingerprint != command_fingerprint:
        raise IdempotencyConflict("idempotency key conflicts with another command")
    return existing


async def finalize_idempotency(
    session: AsyncSession,
    *,
    record: IdempotencyRecord,
    result_type: str,
    result_id: UUID,
    success_status: int,
    result_snapshot: str | None = None,
) -> IdempotencyRecord:
    if not result_type.strip() or not 200 <= success_status <= 299:
        raise ValueError("idempotency finalization is invalid")
    if record.result_id is not None:
        if (
            record.result_type != result_type
            or record.result_id != result_id
            or record.success_status != success_status
        ):
            raise IdempotencyConflict("idempotency record has another logical result")
        return record
    changed = await session.execute(
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.id == record.id,
            IdempotencyRecord.result_id.is_(None),
        )
        .values(
            result_type=result_type.strip(),
            result_id=result_id,
            success_status=success_status,
            result_snapshot=result_snapshot,
            updated_at=func.current_timestamp(),
        )
    )
    if _affected(changed) != 1:
        raise ConcurrencyConflict("idempotency finalization state is stale")
    await session.refresh(record)
    return record


async def create_report_version(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    draft_id: UUID,
    expected_revision: int,
    snapshot: ReportVersionSnapshot | ReportVersionSnapshotV2,
    snapshot_identity: bytes,
    template_version: str,
    idempotency: IdempotencyRecord | None = None,
) -> ReportVersion:
    if idempotency is not None and idempotency.result_id is not None:
        if idempotency.result_type != "report_version":
            raise IdempotencyConflict("idempotency result type does not match report version")
        replay = await get_version(
            session,
            owner_id=owner_id,
            report_id=report_id,
            version_id=idempotency.result_id,
        )
        if replay is None:
            raise IdempotencyConflict("idempotency result is unavailable")
        return replay
    encoded_snapshot = json.dumps(
        snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    if snapshot_identity != sha256(encoded_snapshot).digest():
        raise ValueError("snapshot identity does not match canonical snapshot bytes")
    report = await session.scalar(
        select(Report).where(Report.owner_id == owner_id, Report.id == report_id).with_for_update()
    )
    draft = await session.scalar(
        select(ReportDraft).where(
            ReportDraft.owner_id == owner_id,
            ReportDraft.report_id == report_id,
            ReportDraft.id == draft_id,
            ReportDraft.is_active.is_(True),
            ReportDraft.revision == expected_revision,
        )
    )
    if (
        report is None
        or draft is None
        or snapshot.report_id != report_id
        or snapshot.report_name != report.name
        or snapshot.period_start != report.period_start
        or snapshot.period_end != report.period_end
        or snapshot.template_version != template_version
    ):
        raise ConcurrencyConflict("active draft revision is stale")
    if isinstance(snapshot, ReportVersionSnapshotV2):
        if (
            report.current_dataset_id != snapshot.dataset_id
            or report.current_metric_result_set_id != snapshot.metric_result_set_id
            or report.current_analysis_result_id != snapshot.analysis_result_id
        ):
            raise ConcurrencyConflict("version bindings are no longer current")
    existing = await session.scalar(
        select(ReportVersion).where(
            ReportVersion.owner_id == owner_id,
            ReportVersion.report_id == report_id,
            ReportVersion.snapshot_identity == snapshot_identity,
        )
    )
    if existing is not None:
        if idempotency is not None:
            await finalize_idempotency(
                session,
                record=idempotency,
                result_type="report_version",
                result_id=existing.id,
                success_status=201,
            )
        return existing
    current = await session.scalar(
        select(func.coalesce(func.max(ReportVersion.version_number), 0)).where(
            ReportVersion.report_id == report_id,
            ReportVersion.owner_id == owner_id,
        )
    )
    version = ReportVersion(
        owner_id=owner_id,
        report_id=report_id,
        version_number=int(current or 0) + 1,
        source_draft_id=draft_id,
        source_draft_revision=expected_revision,
        dataset_id=snapshot.dataset_id if isinstance(snapshot, ReportVersionSnapshotV2) else None,
        metric_result_set_id=(
            snapshot.metric_result_set_id if isinstance(snapshot, ReportVersionSnapshotV2) else None
        ),
        analysis_result_id=(
            snapshot.analysis_result_id if isinstance(snapshot, ReportVersionSnapshotV2) else None
        ),
        template_version=template_version,
        snapshot_schema_version=snapshot.schema_version,
        snapshot=snapshot.model_dump(mode="json"),
        snapshot_identity=snapshot_identity,
    )
    session.add(version)
    await session.flush()
    if idempotency is not None:
        await finalize_idempotency(
            session,
            record=idempotency,
            result_type="report_version",
            result_id=version.id,
            success_status=201,
        )
    return version


def report_snapshot_identity(snapshot: ReportVersionSnapshot | ReportVersionSnapshotV2) -> bytes:
    encoded = json.dumps(
        snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return sha256(encoded).digest()


async def get_version(
    session: AsyncSession, *, owner_id: UUID, report_id: UUID, version_id: UUID
) -> ReportVersion | None:
    return await session.scalar(
        select(ReportVersion).where(
            ReportVersion.id == version_id,
            ReportVersion.owner_id == owner_id,
            ReportVersion.report_id == report_id,
        )
    )


async def list_versions(
    session: AsyncSession, *, owner_id: UUID, report_id: UUID
) -> Sequence[ReportVersion]:
    result = await session.scalars(
        select(ReportVersion)
        .where(ReportVersion.owner_id == owner_id, ReportVersion.report_id == report_id)
        .order_by(ReportVersion.version_number.desc(), ReportVersion.id.desc())
    )
    return result.all()


async def list_versions_page(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    limit: int,
    before: tuple[int, UUID] | None = None,
) -> Sequence[ReportVersion]:
    query = select(ReportVersion).where(
        ReportVersion.owner_id == owner_id, ReportVersion.report_id == report_id
    )
    if before is not None:
        query = query.where(
            or_(
                ReportVersion.version_number < before[0],
                and_(ReportVersion.version_number == before[0], ReportVersion.id < before[1]),
            )
        )
    result = await session.scalars(
        query.order_by(ReportVersion.version_number.desc(), ReportVersion.id.desc()).limit(
            limit + 1
        )
    )
    return result.all()


async def restore_version_to_draft(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    version_id: UUID,
    expected_draft_id: UUID | None = None,
    expected_revision: int | None = None,
) -> ReportDraft:
    report = await session.scalar(
        select(Report).where(Report.owner_id == owner_id, Report.id == report_id).with_for_update()
    )
    version = await get_version(
        session, owner_id=owner_id, report_id=report_id, version_id=version_id
    )
    if report is None or version is None:
        raise ConcurrencyConflict("report version is unavailable")
    if expected_draft_id is not None or expected_revision is not None:
        if expected_draft_id is None or expected_revision is None:
            raise ValueError("both expected draft ID and revision are required")
        current_draft = await session.scalar(
            select(ReportDraft).where(
                ReportDraft.owner_id == owner_id,
                ReportDraft.report_id == report_id,
                ReportDraft.id == expected_draft_id,
                ReportDraft.revision == expected_revision,
                ReportDraft.is_active.is_(True),
            )
        )
        if current_draft is None:
            raise ConcurrencyConflict("active draft revision is stale")
    snapshot = parse_report_version_snapshot(version.snapshot)
    await session.execute(
        update(ReportDraft)
        .where(
            ReportDraft.owner_id == owner_id,
            ReportDraft.report_id == report_id,
            ReportDraft.is_active.is_(True),
        )
        .values(is_active=False, updated_at=func.current_timestamp())
    )
    draft = ReportDraft(owner_id=owner_id, report_id=report_id, revision=1, is_active=True)
    session.add(draft)
    await session.flush()
    session.add_all(
        DraftObjective(
            owner_id=owner_id,
            report_id=report_id,
            draft_id=draft.id,
            ordinal=ordinal,
            content=content,
        )
        for ordinal, content in enumerate(snapshot.objectives, start=1)
    )
    session.add_all(
        DraftNarrativeItem(
            owner_id=owner_id,
            report_id=report_id,
            draft_id=draft.id,
            section=item.section,
            ordinal=item.ordinal,
            content=item.content,
            classification=item.classification,
        )
        for item in snapshot.narrative
    )
    session.add_all(
        DraftLimitation(
            owner_id=owner_id,
            report_id=report_id,
            draft_id=draft.id,
            ordinal=ordinal,
            content=content,
        )
        for ordinal, content in enumerate(snapshot.limitations, start=1)
    )
    session.add_all(
        DraftClaim(
            owner_id=owner_id,
            report_id=report_id,
            draft_id=draft.id,
            ordinal=claim.ordinal,
            content=claim.content,
            classification="user_claim",
            source_id=claim.source_id,
        )
        for claim in snapshot.claims
    )
    if isinstance(snapshot, ReportVersionSnapshotV2):
        for ordinal, declaration in enumerate(snapshot.charts, start=1):
            chart = DraftChart(
                owner_id=owner_id,
                report_id=report_id,
                draft_id=draft.id,
                ordinal=ordinal,
                chart_type=declaration.chart_type,
                title=declaration.title,
                x_label=declaration.x_label,
                y_label=declaration.y_label,
                scope=declaration.scope,
            )
            session.add(chart)
            await session.flush()
            session.add_all(
                DraftChartMetricReference(
                    chart_id=chart.id,
                    ordinal=metric_ordinal,
                    metric_result_id=metric_id,
                    owner_id=owner_id,
                    report_id=report_id,
                    draft_id=draft.id,
                )
                for metric_ordinal, metric_id in enumerate(declaration.metric_result_ids, start=1)
            )
    await session.flush()
    return draft


async def create_pdf_export(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    version_id: UUID,
    input_identity: bytes,
) -> PdfExport:
    version = await session.scalar(
        select(ReportVersion)
        .where(
            ReportVersion.id == version_id,
            ReportVersion.owner_id == owner_id,
            ReportVersion.report_id == report_id,
        )
        .with_for_update()
    )
    if version is None:
        raise ConcurrencyConflict("report version is unavailable")
    expected_identity = sha256(
        version.snapshot_identity + version.template_version.encode()
    ).digest()
    if input_identity != expected_identity:
        raise ValueError("PDF input identity does not match the version binding")
    existing = await session.scalar(
        select(PdfExport).where(
            PdfExport.version_id == version_id,
            PdfExport.snapshot_identity == version.snapshot_identity,
            PdfExport.template_version == version.template_version,
        )
    )
    if existing is not None:
        return existing
    export = PdfExport(
        owner_id=owner_id,
        report_id=report_id,
        version_id=version_id,
        snapshot_identity=version.snapshot_identity,
        template_version=version.template_version,
        input_identity=input_identity,
        state="queued",
        attempt_count=1,
    )
    session.add(export)
    await session.flush()
    session.add(
        PdfExportAttempt(
            owner_id=owner_id,
            report_id=report_id,
            export_id=export.id,
            attempt_ordinal=1,
            state="queued",
            queued_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return export


async def claim_pdf_export(
    session: AsyncSession, *, owner_id: UUID, report_id: UUID, export_id: UUID
) -> bool:
    async with session.begin_nested():
        export = await session.scalar(
            select(PdfExport)
            .where(
                PdfExport.id == export_id,
                PdfExport.owner_id == owner_id,
                PdfExport.report_id == report_id,
            )
            .with_for_update()
        )
        if export is None or export.state != "queued":
            return False
        now = datetime.now(UTC)
        changed = await session.execute(
            update(PdfExportAttempt)
            .where(
                PdfExportAttempt.export_id == export_id,
                PdfExportAttempt.attempt_ordinal == export.attempt_count,
                PdfExportAttempt.state == "queued",
            )
            .values(state="running", started_at=now)
        )
        if _affected(changed) != 1:
            raise ConcurrencyConflict("PDF attempt state is stale")
        export.state = "running"
        export.updated_at = now
        await session.flush()
        return True


async def finish_pdf_export(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    export_id: UUID,
    expected_attempt_count: int,
    asset: FileAsset,
) -> FileAsset:
    async with session.begin_nested():
        export = await session.scalar(
            select(PdfExport)
            .where(
                PdfExport.id == export_id,
                PdfExport.owner_id == owner_id,
                PdfExport.report_id == report_id,
            )
            .with_for_update()
        )
        if export is None or export.attempt_count != expected_attempt_count:
            raise ConcurrencyConflict("PDF completion state is stale")
        if (
            asset.owner_id != owner_id
            or asset.report_id != report_id
            or asset.purpose != "generated_pdf"
            or asset.content_type != "application/pdf"
            or asset.byte_size <= 0
        ):
            raise ValueError("generated PDF asset binding is invalid")
        asset.version_id = export.version_id
        asset.export_id = export.id
        if export.state == "succeeded" and export.generated_asset_id is not None:
            existing = await session.scalar(
                select(FileAsset).where(
                    FileAsset.id == export.generated_asset_id,
                    FileAsset.owner_id == owner_id,
                    FileAsset.report_id == report_id,
                )
            )
            if existing is None or not file_asset_metadata_matches(existing, asset):
                raise ConcurrencyConflict("PDF asset binding conflicts with existing metadata")
            return existing
        if export.state != "running":
            raise ConcurrencyConflict("PDF completion state is stale")
        session.add(asset)
        await session.flush()
        now = datetime.now(UTC)
        changed = await session.execute(
            update(PdfExportAttempt)
            .where(
                PdfExportAttempt.export_id == export_id,
                PdfExportAttempt.attempt_ordinal == expected_attempt_count,
                PdfExportAttempt.state == "running",
            )
            .values(state="succeeded", finished_at=now)
        )
        if _affected(changed) != 1:
            raise ConcurrencyConflict("PDF attempt completion state is stale")
        export.state = "succeeded"
        export.generated_asset_id = asset.id
        export.generated_asset_purpose = asset.purpose
        export.updated_at = now
        await session.flush()
        return asset


async def fail_pdf_export(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    export_id: UUID,
    expected_attempt_count: int,
    failure_code: str,
    failure_message: str,
    retryable: bool,
) -> None:
    safe_code, safe_message = _sanitized_failure(failure_code, failure_message)
    async with session.begin_nested():
        now = datetime.now(UTC)
        changed = await session.execute(
            update(PdfExport)
            .where(
                PdfExport.id == export_id,
                PdfExport.owner_id == owner_id,
                PdfExport.report_id == report_id,
                PdfExport.state == "running",
                PdfExport.attempt_count == expected_attempt_count,
            )
            .values(
                state="failed",
                failure_code=safe_code,
                failure_message=safe_message,
                failure_retryable=retryable,
                updated_at=now,
            )
        )
        attempt_changed = await session.execute(
            update(PdfExportAttempt)
            .where(
                PdfExportAttempt.export_id == export_id,
                PdfExportAttempt.attempt_ordinal == expected_attempt_count,
                PdfExportAttempt.state == "running",
            )
            .values(
                state="failed",
                finished_at=now,
                failure_code=safe_code,
                failure_message=safe_message,
                failure_retryable=retryable,
            )
        )
        if _affected(changed) != 1 or _affected(attempt_changed) != 1:
            raise ConcurrencyConflict("PDF failure state is stale")


async def get_pdf_export(
    session: AsyncSession, *, owner_id: UUID, report_id: UUID, export_id: UUID
) -> PdfExport | None:
    return await session.scalar(
        select(PdfExport).where(
            PdfExport.id == export_id,
            PdfExport.owner_id == owner_id,
            PdfExport.report_id == report_id,
        )
    )


async def get_pdf_asset(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    version_id: UUID,
    export_id: UUID,
) -> PdfAssetAggregate | None:
    row = (
        await session.execute(
            select(PdfExport, ReportVersion, FileAsset)
            .join(
                ReportVersion,
                (ReportVersion.id == PdfExport.version_id)
                & (ReportVersion.owner_id == PdfExport.owner_id)
                & (ReportVersion.report_id == PdfExport.report_id),
            )
            .outerjoin(
                FileAsset,
                (FileAsset.id == PdfExport.generated_asset_id)
                & (FileAsset.owner_id == PdfExport.owner_id)
                & (FileAsset.report_id == PdfExport.report_id),
            )
            .where(
                PdfExport.owner_id == owner_id,
                PdfExport.report_id == report_id,
                PdfExport.version_id == version_id,
                PdfExport.id == export_id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return PdfAssetAggregate(export=row[0], version=row[1], asset=row[2])


async def list_pdf_exports(
    session: AsyncSession, *, owner_id: UUID, report_id: UUID, version_id: UUID
) -> Sequence[PdfExport]:
    result = await session.scalars(
        select(PdfExport)
        .where(
            PdfExport.owner_id == owner_id,
            PdfExport.report_id == report_id,
            PdfExport.version_id == version_id,
        )
        .order_by(PdfExport.created_at.desc(), PdfExport.id.desc())
    )
    return result.all()


async def retry_pdf_export(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    export_id: UUID,
    expected_attempt_count: int,
) -> int:
    async with session.begin_nested():
        export = await session.scalar(
            select(PdfExport)
            .where(
                PdfExport.owner_id == owner_id,
                PdfExport.report_id == report_id,
                PdfExport.id == export_id,
            )
            .with_for_update()
        )
        if (
            export is None
            or export.state != "failed"
            or export.failure_retryable is not True
            or export.attempt_count != expected_attempt_count
        ):
            raise ConcurrencyConflict("PDF retry state is stale")
        next_ordinal = expected_attempt_count + 1
        export.state = "queued"
        export.attempt_count = next_ordinal
        export.failure_code = None
        export.failure_message = None
        export.failure_retryable = None
        session.add(
            PdfExportAttempt(
                owner_id=owner_id,
                report_id=report_id,
                export_id=export_id,
                attempt_ordinal=next_ordinal,
                state="queued",
                queued_at=datetime.now(UTC),
            )
        )
        await session.flush()
        return next_ordinal
