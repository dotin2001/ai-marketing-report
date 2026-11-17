"""Build saved report versions from owner-scoped current database state."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AnalysisItemClaimReference,
    AnalysisItemMetricReference,
    AnalysisJob,
    AnalysisResult,
    AnalysisResultItem,
    CanonicalDataset,
    ConfirmedImport,
    DatasetCurrency,
    DraftChart,
    DraftChartMetricReference,
    DraftClaim,
    DraftLimitation,
    DraftNarrativeItem,
    DraftObjective,
    ImportColumnMapping,
    ImportConfiguration,
    ImportConfigurationRevision,
    ImportValidation,
    ImportValidationIssue,
    MetricResult,
    MetricResultCurrency,
    MetricResultInput,
    MetricResultSet,
    Report,
    ReportDraft,
    ReportSource,
    ReportVersion,
    SourceReviewConfirmation,
)
from app.db.repositories import (
    ConcurrencyConflict,
    create_report_version,
    finalize_idempotency,
    get_version,
    report_snapshot_identity,
    resolve_idempotency,
    restore_version_to_draft,
)
from app.db.snapshots import ReportVersionSnapshotV2


async def _rows(
    session: AsyncSession,
    model: type[Any],
    owner_id: UUID,
    report_id: UUID,
    field: str,
    value: UUID,
    *order: Any,
) -> list[Any]:
    query: Any = select(model).where(
        model.owner_id == owner_id,
        model.report_id == report_id,
        getattr(model, field) == value,
    )
    if order:
        query = query.order_by(*order)
    return list((await session.scalars(query)).all())


async def save_current_report_version(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    draft_id: UUID,
    expected_revision: int,
    template_version: str,
    idempotency_key: str,
) -> ReportVersion:
    """Save one coherent schema 2 snapshot within the caller's transaction."""
    fingerprint = sha256(
        json.dumps(
            {
                "report": str(report_id),
                "draft": str(draft_id),
                "revision": expected_revision,
                "template": template_version,
            },
            sort_keys=True,
        ).encode()
    ).digest()
    record = await resolve_idempotency(
        session,
        principal_id=owner_id,
        operation="create-version-v2",
        scope_kind="report",
        scope_id=report_id,
        raw_key=idempotency_key,
        command_fingerprint=fingerprint,
    )
    if record.result_id is not None:
        replay = await get_version(
            session, owner_id=owner_id, report_id=report_id, version_id=record.result_id
        )
        if replay is None or record.result_type != "report_version":
            raise ConcurrencyConflict("saved version replay is unavailable")
        return replay
    report = await session.scalar(
        select(Report)
        .where(
            Report.id == report_id,
            Report.owner_id == owner_id,
        )
        .with_for_update()
    )
    draft = await session.scalar(
        select(ReportDraft).where(
            ReportDraft.id == draft_id,
            ReportDraft.report_id == report_id,
            ReportDraft.owner_id == owner_id,
            ReportDraft.is_active.is_(True),
            ReportDraft.revision == expected_revision,
        )
    )
    if report is None or draft is None or report.current_source_id is None:
        raise ConcurrencyConflict("active draft or source is unavailable")
    source = await session.scalar(
        select(ReportSource).where(
            ReportSource.id == report.current_source_id,
            ReportSource.report_id == report_id,
            ReportSource.owner_id == owner_id,
        )
    )
    if source is None:
        raise ConcurrencyConflict("current source is unavailable")
    source_data = {
        "source_id": source.id,
        "source_type": source.source_type,
        "checksum_sha256": source.checksum_sha256.hex(),
        "byte_size": source.byte_size,
        "media_type": source.media_type,
        "display_filename": source.display_filename,
    }
    confirmed_data = None
    canonical_identity = None
    dataset_id = None
    metric_set_id = None
    metrics: list[dict[str, Any]] = []
    metric_set: MetricResultSet | None = None
    if source.source_type == "text":
        confirmation = await session.scalar(
            select(SourceReviewConfirmation).where(
                SourceReviewConfirmation.owner_id == owner_id,
                SourceReviewConfirmation.report_id == report_id,
                SourceReviewConfirmation.source_id == source.id,
                SourceReviewConfirmation.source_checksum == source.checksum_sha256,
            )
        )
        if (
            confirmation is None
            or report.current_dataset_id is not None
            or report.current_metric_result_set_id is not None
        ):
            raise ConcurrencyConflict("text source review or structured bindings are unavailable")
    else:
        dataset = await session.scalar(
            select(CanonicalDataset).where(
                CanonicalDataset.id == report.current_dataset_id,
                CanonicalDataset.owner_id == owner_id,
                CanonicalDataset.report_id == report_id,
                CanonicalDataset.source_id == source.id,
            )
        )
        if dataset is None:
            raise ConcurrencyConflict("current confirmed dataset is unavailable")
        confirmation = await session.scalar(
            select(ConfirmedImport).where(
                ConfirmedImport.id == dataset.confirmation_id,
                ConfirmedImport.owner_id == owner_id,
                ConfirmedImport.report_id == report_id,
            )
        )
        if confirmation is None or (
            confirmation.canonical_data_identity != dataset.canonical_data_identity
            or confirmation.row_count != dataset.row_count
            or confirmation.period_start != dataset.period_start
            or confirmation.period_end != dataset.period_end
            or report.period_start != dataset.period_start
            or report.period_end != dataset.period_end
        ):
            raise ConcurrencyConflict("dataset confirmation does not match")
        configuration = await session.scalar(
            select(ImportConfiguration).where(
                ImportConfiguration.id == confirmation.configuration_id,
                ImportConfiguration.owner_id == owner_id,
                ImportConfiguration.report_id == report_id,
                ImportConfiguration.source_id == source.id,
                ImportConfiguration.current_revision == confirmation.revision,
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
        validation = await session.scalar(
            select(ImportValidation).where(
                ImportValidation.id == confirmation.validation_id,
                ImportValidation.owner_id == owner_id,
                ImportValidation.report_id == report_id,
                ImportValidation.error_count == 0,
            )
        )
        if (
            configuration is None
            or revision is None
            or validation is None
            or revision.normalization_policy_version != dataset.normalization_policy_version
        ):
            raise ConcurrencyConflict("current import provenance does not match")
        mappings = await _rows(
            session,
            ImportColumnMapping,
            owner_id,
            report_id,
            "configuration_id",
            configuration.id,
            ImportColumnMapping.source_column_ordinal,
        )
        mappings = [mapping for mapping in mappings if mapping.revision == confirmation.revision]
        issues = await _rows(
            session,
            ImportValidationIssue,
            owner_id,
            report_id,
            "validation_id",
            validation.id,
            ImportValidationIssue.ordinal,
        )
        if any(issue.severity == "error" for issue in issues):
            raise ConcurrencyConflict("confirmed validation contains errors")
        currencies = await _rows(
            session,
            DatasetCurrency,
            owner_id,
            report_id,
            "dataset_id",
            dataset.id,
            DatasetCurrency.currency,
        )
        confirmed_data = {
            "confirmation_id": confirmation.id,
            "configuration_id": configuration.id,
            "configuration_revision": confirmation.revision,
            "normalization_policy_version": revision.normalization_policy_version,
            "date_format": revision.date_format,
            "mappings": [
                {
                    "source_column_ordinal": mapping.source_column_ordinal,
                    "canonical_field": mapping.canonical_field,
                }
                for mapping in mappings
            ],
            "validation_id": validation.id,
            "warning_codes": [issue.code for issue in issues if issue.severity == "warning"],
            "canonical_data_identity": dataset.canonical_data_identity.hex(),
            "row_count": dataset.row_count,
            "currencies": [item.currency for item in currencies],
        }
        canonical_identity = dataset.canonical_data_identity.hex()
        dataset_id = dataset.id
        if report.current_metric_result_set_id is not None:
            metric_set = await session.scalar(
                select(MetricResultSet).where(
                    MetricResultSet.id == report.current_metric_result_set_id,
                    MetricResultSet.owner_id == owner_id,
                    MetricResultSet.report_id == report_id,
                    MetricResultSet.dataset_id == dataset.id,
                )
            )
            if metric_set is None:
                raise ConcurrencyConflict("current metric result set does not match dataset")
            metric_set_id = metric_set.id
            for metric in await _rows(
                session,
                MetricResult,
                owner_id,
                report_id,
                "result_set_id",
                metric_set.id,
                MetricResult.metric_name,
                MetricResult.id,
            ):
                inputs = await _rows(
                    session,
                    MetricResultInput,
                    owner_id,
                    report_id,
                    "metric_result_id",
                    metric.id,
                    MetricResultInput.ordinal,
                )
                metric_currencies = await _rows(
                    session,
                    MetricResultCurrency,
                    owner_id,
                    report_id,
                    "metric_result_id",
                    metric.id,
                    MetricResultCurrency.currency,
                )
                metrics.append(
                    {
                        "metric_result_id": metric.id,
                        "name": metric.metric_name,
                        "availability": metric.availability,
                        "value": str(metric.value) if metric.value is not None else None,
                        "unit": metric.unit,
                        "unavailable_reason": metric.unavailable_reason,
                        "exact_inputs": {item.input_name: str(item.exact_total) for item in inputs},
                        "represented_currencies": [item.currency for item in metric_currencies],
                        "scope": metric.scope,
                        "period_start": metric.period_start,
                        "period_end": metric.period_end,
                        "currency": metric.currency,
                        "calculation_version": metric_set.calculation_version,
                    }
                )
            if not metrics:
                raise ConcurrencyConflict("current metric result set is empty")
    objectives = await _rows(
        session, DraftObjective, owner_id, report_id, "draft_id", draft_id, DraftObjective.ordinal
    )
    narrative = await _rows(
        session,
        DraftNarrativeItem,
        owner_id,
        report_id,
        "draft_id",
        draft_id,
        DraftNarrativeItem.section,
        DraftNarrativeItem.ordinal,
    )
    limitations = await _rows(
        session, DraftLimitation, owner_id, report_id, "draft_id", draft_id, DraftLimitation.ordinal
    )
    claims = await _rows(
        session, DraftClaim, owner_id, report_id, "draft_id", draft_id, DraftClaim.ordinal
    )
    included_metric_ids = {metric["metric_result_id"] for metric in metrics}
    metric_scopes = {metric["metric_result_id"]: metric["scope"] for metric in metrics}
    current_claim_ids = {claim.id for claim in claims}
    charts = []
    for chart in await _rows(
        session, DraftChart, owner_id, report_id, "draft_id", draft_id, DraftChart.ordinal
    ):
        refs = await _rows(
            session,
            DraftChartMetricReference,
            owner_id,
            report_id,
            "chart_id",
            chart.id,
            DraftChartMetricReference.ordinal,
        )
        if not refs or any(
            ref.metric_result_id not in included_metric_ids
            or metric_scopes[ref.metric_result_id] != chart.scope
            for ref in refs
        ):
            raise ConcurrencyConflict("draft chart references stale metrics")
        charts.append(
            {
                "chart_type": chart.chart_type,
                "title": chart.title,
                "x_label": chart.x_label,
                "y_label": chart.y_label,
                "scope": chart.scope,
                "metric_result_ids": [ref.metric_result_id for ref in refs],
            }
        )
    analysis_data = None
    analysis_id = report.current_analysis_result_id
    if analysis_id is not None:
        result = await session.scalar(
            select(AnalysisResult).where(
                AnalysisResult.id == analysis_id,
                AnalysisResult.owner_id == owner_id,
                AnalysisResult.report_id == report_id,
            )
        )
        job = (
            await session.scalar(
                select(AnalysisJob).where(
                    AnalysisJob.id == result.job_id,
                    AnalysisJob.owner_id == owner_id,
                    AnalysisJob.report_id == report_id,
                )
            )
            if result is not None
            else None
        )
        if (
            result is None
            or job is None
            or metric_set_id is None
            or job.state != "succeeded"
            or job.current_result_id != analysis_id
            or job.draft_id != draft_id
            or job.dataset_id != dataset_id
            or job.metric_result_set_id != metric_set_id
            or result.semantic_input_identity != job.semantic_input_identity
            or metric_set is None
            or result.numeric_source_identity != metric_set.identity
        ):
            raise ConcurrencyConflict("current analysis does not match the saved inputs")
        items = []
        for item in await _rows(
            session,
            AnalysisResultItem,
            owner_id,
            report_id,
            "result_id",
            analysis_id,
            AnalysisResultItem.section,
            AnalysisResultItem.ordinal,
        ):
            item_metrics = await _rows(
                session, AnalysisItemMetricReference, owner_id, report_id, "item_id", item.id
            )
            item_claims = await _rows(
                session, AnalysisItemClaimReference, owner_id, report_id, "item_id", item.id
            )
            if any(ref.metric_result_id not in included_metric_ids for ref in item_metrics) or any(
                ref.claim_id not in current_claim_ids for ref in item_claims
            ):
                raise ConcurrencyConflict("analysis references stale draft or metric inputs")
            items.append(
                {
                    "section": item.section,
                    "ordinal": item.ordinal,
                    "classification": item.classification,
                    "content": item.content,
                    "metric_result_ids": [ref.metric_result_id for ref in item_metrics],
                    "claim_ids": [ref.claim_id for ref in item_claims],
                }
            )
        analysis_data = {
            "result_id": result.id,
            "model_identifier": result.model_identifier,
            "prompt_version": result.prompt_version,
            "request_provenance": result.request_provenance,
            "semantic_input_identity": result.semantic_input_identity.hex(),
            "numeric_source_identity": result.numeric_source_identity.hex(),
            "items": items,
        }
    snapshot = ReportVersionSnapshotV2.model_validate(
        {
            "schema_version": 2,
            "report_id": report_id,
            "report_name": report.name,
            "period_start": report.period_start,
            "period_end": report.period_end,
            "objectives": [item.content for item in objectives],
            "source": source_data,
            "confirmed_import": confirmed_data,
            "canonical_data_identity": canonical_identity,
            "dataset_id": dataset_id,
            "metric_result_set_id": metric_set_id,
            "analysis_result_id": analysis_id,
            "metrics": metrics,
            "analysis": analysis_data,
            "narrative": [
                {
                    "item_id": item.id,
                    "section": item.section,
                    "ordinal": item.ordinal,
                    "classification": item.classification,
                    "content": item.content,
                }
                for item in narrative
            ],
            "limitations": [item.content for item in limitations],
            "claims": [
                {
                    "claim_id": item.id,
                    "ordinal": item.ordinal,
                    "content": item.content,
                    "source_id": item.source_id,
                }
                for item in claims
            ],
            "charts": charts,
            "template_version": template_version,
        }
    )
    return await create_report_version(
        session,
        owner_id=owner_id,
        report_id=report_id,
        draft_id=draft_id,
        expected_revision=expected_revision,
        snapshot=snapshot,
        snapshot_identity=report_snapshot_identity(snapshot),
        template_version=template_version,
        idempotency=record,
    )


async def restore_saved_version(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    version_id: UUID,
    expected_draft_id: UUID,
    expected_revision: int,
    idempotency_key: str,
) -> ReportDraft:
    """Copy editable saved fields into a new active draft, with scoped replay."""
    fingerprint = sha256(
        json.dumps(
            {
                "report": str(report_id),
                "version": str(version_id),
                "draft": str(expected_draft_id),
                "revision": expected_revision,
            },
            sort_keys=True,
        ).encode()
    ).digest()
    record = await resolve_idempotency(
        session,
        principal_id=owner_id,
        operation="restore-version-v2",
        scope_kind="report",
        scope_id=report_id,
        raw_key=idempotency_key,
        command_fingerprint=fingerprint,
    )
    if record.result_id is not None:
        replay = await session.scalar(
            select(ReportDraft).where(
                ReportDraft.id == record.result_id,
                ReportDraft.owner_id == owner_id,
                ReportDraft.report_id == report_id,
            )
        )
        if replay is None or record.result_type != "report_draft":
            raise ConcurrencyConflict("restored draft replay is unavailable")
        return replay
    restored = await restore_version_to_draft(
        session,
        owner_id=owner_id,
        report_id=report_id,
        version_id=version_id,
        expected_draft_id=expected_draft_id,
        expected_revision=expected_revision,
    )
    await finalize_idempotency(
        session,
        record=record,
        result_type="report_draft",
        result_id=restored.id,
        success_status=201,
    )
    return restored
