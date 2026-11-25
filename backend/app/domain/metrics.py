"""Persist one immutable KPI result set for a current confirmed dataset."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CanonicalDataset,
    CanonicalRow,
    MetricResult,
    MetricResultCurrency,
    MetricResultInput,
    MetricResultSet,
    Report,
)
from app.db.repositories import ConcurrencyConflict
from app.domain.assets import ResourceNotFound
from app.processing.kpi_calculation import CALCULATION_VERSION, calculate_kpis, result_set_identity


async def ensure_current_metrics(
    session: AsyncSession, *, owner_id: UUID, report_id: UUID, dataset_id: UUID
) -> MetricResultSet:
    report = await session.scalar(
        select(Report)
        .where(Report.id == report_id, Report.owner_id == owner_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if report is None:
        raise ResourceNotFound
    dataset = await session.scalar(
        select(CanonicalDataset).where(
            CanonicalDataset.id == dataset_id,
            CanonicalDataset.report_id == report_id,
            CanonicalDataset.owner_id == owner_id,
        )
    )
    if dataset is None or report.current_dataset_id != dataset.id:
        raise ConcurrencyConflict("confirmed dataset is no longer current")
    identity = result_set_identity(dataset.canonical_data_identity)
    existing = await session.scalar(
        select(MetricResultSet).where(MetricResultSet.identity == identity)
    )
    if existing is not None:
        if (
            existing.dataset_id != dataset.id
            or existing.owner_id != owner_id
            or existing.report_id != report_id
        ):
            raise ConcurrencyConflict("metric identity conflicts with confirmed dataset")
        report.current_metric_result_set_id = existing.id
        return existing
    rows = (
        await session.scalars(
            select(CanonicalRow)
            .where(
                CanonicalRow.dataset_id == dataset.id,
                CanonicalRow.report_id == report_id,
                CanonicalRow.owner_id == owner_id,
            )
            .order_by(CanonicalRow.source_record_index, CanonicalRow.id)
        )
    ).all()
    if len(rows) != dataset.row_count:
        raise ConcurrencyConflict("confirmed dataset row count changed")
    calculated = calculate_kpis(
        rows, period_start=dataset.period_start, period_end=dataset.period_end
    )
    metric_set = MetricResultSet(
        owner_id=owner_id,
        report_id=report_id,
        dataset_id=dataset.id,
        identity=identity,
        calculation_version=CALCULATION_VERSION,
        calculated_at=datetime.now(UTC),
    )
    session.add(metric_set)
    await session.flush()
    for item in calculated:
        result = MetricResult(
            owner_id=owner_id,
            report_id=report_id,
            result_set_id=metric_set.id,
            metric_name=item.metric_name,
            availability="available" if item.value is not None else "unavailable",
            scope=item.scope,
            group_identity=item.group_identity,
            campaign_name=item.campaign_name,
            period_start=item.period_start,
            period_end=item.period_end,
            currency=item.currency,
            value=Decimal(item.value) if item.value is not None else None,
            unit=item.unit,
            unavailable_reason=item.unavailable_reason,
            supporting_field=item.supporting_field,
        )
        session.add(result)
        await session.flush()
        session.add_all(
            MetricResultInput(
                owner_id=owner_id,
                report_id=report_id,
                metric_result_id=result.id,
                ordinal=ordinal,
                input_name=name,
                exact_total=Decimal(total),
            )
            for ordinal, (name, total) in enumerate(item.inputs, 1)
        )
        session.add_all(
            MetricResultCurrency(
                owner_id=owner_id,
                report_id=report_id,
                metric_result_id=result.id,
                currency=currency,
            )
            for currency in item.represented_currencies
        )
    await session.flush()
    if report.current_dataset_id != dataset.id:
        raise ConcurrencyConflict("confirmed dataset changed during calculation")
    report.current_metric_result_set_id = metric_set.id
    return metric_set
