"""Owner-scoped reads of immutable canonical rows and metric provenance."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dataset_schemas import (
    AvailableMetric,
    CanonicalRowDetail,
    DatasetDetail,
    MetricDetail,
    UnavailableMetric,
)
from app.db.models import (
    CanonicalDataset,
    CanonicalRow,
    DatasetCurrency,
    MetricResult,
    MetricResultCurrency,
    MetricResultInput,
    MetricResultSet,
    Report,
)
from app.domain.assets import ResourceNotFound
from app.processing.kpi_calculation import CALCULATION_VERSION, metric_order_key


class DatasetReadServices:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _dataset(
        self,
        session: AsyncSession,
        owner_id: UUID,
        report_id: UUID,
        dataset_id: UUID | None,
    ) -> tuple[CanonicalDataset, Report]:
        report = await session.scalar(
            select(Report).where(
                Report.id == report_id,
                Report.owner_id == owner_id,
            )
        )
        if report is None:
            raise ResourceNotFound
        target = dataset_id or report.current_dataset_id
        dataset = await session.scalar(
            select(CanonicalDataset).where(
                CanonicalDataset.id == target,
                CanonicalDataset.owner_id == owner_id,
                CanonicalDataset.report_id == report_id,
            )
        )
        if dataset is None:
            raise ResourceNotFound
        return dataset, report

    async def detail(
        self,
        owner_id: UUID,
        report_id: UUID,
        dataset_id: UUID | None = None,
    ) -> DatasetDetail:
        async with self.sessions() as session:
            dataset, _ = await self._dataset(session, owner_id, report_id, dataset_id)
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
            metric_set = await session.scalar(
                select(MetricResultSet).where(
                    MetricResultSet.dataset_id == dataset.id,
                    MetricResultSet.owner_id == owner_id,
                    MetricResultSet.report_id == report_id,
                    MetricResultSet.calculation_version == CALCULATION_VERSION,
                )
            )
            return DatasetDetail(
                id=dataset.id,
                report_id=report_id,
                source_id=dataset.source_id,
                confirmation_id=dataset.confirmation_id,
                canonical_data_identity=dataset.canonical_data_identity.hex(),
                normalization_policy_version=dataset.normalization_policy_version,
                period_start=dataset.period_start,
                period_end=dataset.period_end,
                total_records=dataset.row_count,
                accepted_row_count=dataset.row_count,
                rejected_row_count=0,
                row_count_explanation=(
                    "All source records were accepted, including warned duplicates."
                ),
                currencies=currencies,
                metric_result_set_id=metric_set.id if metric_set else None,
            )

    async def rows(
        self,
        owner_id: UUID,
        report_id: UUID,
        dataset_id: UUID,
        offset: int,
        limit: int,
    ) -> tuple[list[CanonicalRowDetail], int | None, int]:
        async with self.sessions() as session:
            dataset, _ = await self._dataset(session, owner_id, report_id, dataset_id)
            rows = (
                await session.scalars(
                    select(CanonicalRow)
                    .where(
                        CanonicalRow.dataset_id == dataset.id,
                        CanonicalRow.owner_id == owner_id,
                        CanonicalRow.report_id == report_id,
                    )
                    .order_by(CanonicalRow.source_record_index, CanonicalRow.id)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            details = [
                CanonicalRowDetail(
                    id=row.id,
                    source_record_index=row.source_record_index,
                    date=row.row_date,
                    campaign_name=row.campaign_name,
                    currency=row.currency,
                    impressions=row.impressions,
                    clicks=row.clicks,
                    spend=format(row.spend, "f") if row.spend is not None else None,
                    leads=row.leads,
                )
                for row in rows
            ]
            next_offset = offset + len(rows) if offset + len(rows) < dataset.row_count else None
            return details, next_offset, dataset.row_count

    async def metrics(
        self,
        owner_id: UUID,
        report_id: UUID,
        dataset_id: UUID,
        scope: str | None,
        campaign_name: str | None,
        currency: str | None,
    ) -> tuple[list[MetricDetail], UUID]:
        async with self.sessions() as session:
            dataset, _ = await self._dataset(session, owner_id, report_id, dataset_id)
            metric_set = await session.scalar(
                select(MetricResultSet).where(
                    MetricResultSet.dataset_id == dataset.id,
                    MetricResultSet.owner_id == owner_id,
                    MetricResultSet.report_id == report_id,
                    MetricResultSet.calculation_version == CALCULATION_VERSION,
                )
            )
            if metric_set is None:
                raise ResourceNotFound
            query = select(MetricResult).where(
                MetricResult.result_set_id == metric_set.id,
                MetricResult.owner_id == owner_id,
                MetricResult.report_id == report_id,
            )
            if scope is not None:
                query = query.where(MetricResult.scope == scope)
            if campaign_name is not None:
                query = query.where(MetricResult.campaign_name == campaign_name)
            if currency is not None:
                query = query.where(MetricResult.currency == currency)
            results = list((await session.scalars(query)).all())
            results.sort(
                key=lambda item: (
                    *metric_order_key(
                        item.scope, item.campaign_name, item.metric_name, item.currency
                    ),
                    str(item.id),
                )
            )
            details: list[MetricDetail] = []
            for result in results:
                inputs = (
                    await session.scalars(
                        select(MetricResultInput)
                        .where(
                            MetricResultInput.metric_result_id == result.id,
                            MetricResultInput.owner_id == owner_id,
                            MetricResultInput.report_id == report_id,
                        )
                        .order_by(MetricResultInput.ordinal)
                    )
                ).all()
                represented = list(
                    (
                        await session.scalars(
                            select(MetricResultCurrency.currency)
                            .where(
                                MetricResultCurrency.metric_result_id == result.id,
                                MetricResultCurrency.owner_id == owner_id,
                                MetricResultCurrency.report_id == report_id,
                            )
                            .order_by(MetricResultCurrency.currency)
                        )
                    ).all()
                )
                common = dict(
                    id=result.id,
                    metric_name=result.metric_name,
                    scope=result.scope,
                    group_identity=result.group_identity,
                    campaign_name=result.campaign_name,
                    currency=result.currency,
                    represented_currencies=represented,
                    period_start=result.period_start,
                    period_end=result.period_end,
                    canonical_data_identity=dataset.canonical_data_identity.hex(),
                    calculation_version=metric_set.calculation_version,
                    calculated_at=metric_set.calculated_at,
                    inputs={item.input_name: format(item.exact_total, "f") for item in inputs},
                )
                if result.availability == "available":
                    assert result.value is not None and result.unit is not None
                    details.append(
                        AvailableMetric.model_validate(
                            {
                                **common,
                                "availability": "available",
                                "value": format(result.value, "f"),
                                "unit": result.unit,
                            }
                        )
                    )
                else:
                    assert result.unavailable_reason is not None
                    details.append(
                        UnavailableMetric.model_validate(
                            {
                                **common,
                                "availability": "unavailable",
                                "unavailable_reason": result.unavailable_reason,
                                "supporting_field": result.supporting_field,
                            }
                        )
                    )
            return details, metric_set.id
