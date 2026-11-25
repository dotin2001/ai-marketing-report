"""Revision-bound, bounded numeric context for analysis."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AnalysisJob,
    DatasetCurrency,
    DraftObjective,
    MetricResult,
    MetricResultCurrency,
    MetricResultInput,
    Report,
    ReportSource,
)
from app.db.repositories import ConcurrencyConflict
from app.domain.analysis_jobs import current_analysis_input

CONTEXT_VERSION = "analysis-context-v1"
MAX_OBJECTIVES = 20
MAX_OBJECTIVE_CHARS = 1000
MAX_METRICS = 200
MAX_CONTEXT_BYTES = 65536


class ContextBudgetExceeded(Exception):
    """Current inputs cannot fit the versioned analysis budget."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Period(StrictModel):
    start: date
    end: date

    @model_validator(mode="after")
    def valid_order(self) -> Period:
        if self.end < self.start:
            raise ValueError("invalid period")
        return self


class Objective(StrictModel):
    ordinal: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=MAX_OBJECTIVE_CHARS)

    @field_validator("content")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("blank objective")
        return value


class ExactTotal(StrictModel):
    ordinal: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=32)
    value: str

    @field_validator("value")
    @classmethod
    def finite_decimal(cls, value: str) -> str:
        if not value or value.strip() != value:
            raise ValueError("invalid decimal")
        try:
            if not Decimal(value).is_finite():
                raise ValueError("non-finite decimal")
        except InvalidOperation as error:
            raise ValueError("invalid decimal") from error
        return value


class PreparedMetric(StrictModel):
    id: UUID
    name: Literal["ctr", "cpc", "cpm", "cpl"]
    availability: Literal["available", "unavailable"]
    value: str | None
    unit: str | None
    unavailable_reason: str | None
    supporting_field: str | None
    scope: Literal["report", "currency", "campaign"]
    group_identity: str
    campaign_name: str | None
    period: Period
    currency: str | None
    represented_currencies: list[str]
    inputs: list[ExactTotal]
    calculation_version: str
    result_set_id: UUID
    numeric_source_identity: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: str | None) -> str | None:
        return ExactTotal.finite_decimal(value) if value is not None else None

    @model_validator(mode="after")
    def valid_availability(self) -> PreparedMetric:
        if self.availability == "available":
            if self.value is None or self.unit is None or self.unavailable_reason is not None:
                raise ValueError("invalid available metric")
        elif self.value is not None or self.unit is not None or self.unavailable_reason is None:
            raise ValueError("invalid unavailable metric")
        if self.represented_currencies != sorted(set(self.represented_currencies)):
            raise ValueError("currencies must be sorted and unique")
        return self


class PreparedContext(StrictModel):
    version: Literal["analysis-context-v1"]
    owner_id: UUID
    report_id: UUID
    job_id: UUID
    source_id: UUID
    source_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation_id: UUID
    dataset_id: UUID
    canonical_data_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_set_id: UUID
    numeric_source_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_input_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft_id: UUID
    draft_revision: int = Field(ge=1)
    objectives_revision: int = Field(ge=1)
    period: Period
    represented_currencies: list[str]
    objectives: list[Objective] = Field(max_length=MAX_OBJECTIVES)
    metrics: list[PreparedMetric] = Field(max_length=MAX_METRICS)

    @model_validator(mode="after")
    def valid_order(self) -> PreparedContext:
        if [o.ordinal for o in self.objectives] != list(range(1, len(self.objectives) + 1)):
            raise ValueError("objective order is invalid")
        if len({m.id for m in self.metrics}) != len(self.metrics):
            raise ValueError("duplicate metric")
        return self


def exact(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("non-finite decimal")
    return str(value)


async def prepare_context(session: AsyncSession, job: AnalysisJob) -> PreparedContext:
    owner_id, report_id = job.owner_id, job.report_id
    report = await session.scalar(
        select(Report).where(Report.id == report_id, Report.owner_id == owner_id)
    )
    if report is None:
        raise ConcurrencyConflict("analysis input is stale")
    draft, dataset, result_set, identity = await current_analysis_input(
        session, report, job.draft_revision, job.dataset_id, job.metric_result_set_id
    )
    if (
        draft.id != job.draft_id
        or draft.objectives_revision != job.objectives_revision
        or identity != job.semantic_input_identity
        or dataset.period_start != report.period_start
        or dataset.period_end != report.period_end
        or report.current_source_id != dataset.source_id
    ):
        raise ConcurrencyConflict("analysis input is stale")
    source = await session.scalar(
        select(ReportSource).where(
            ReportSource.id == dataset.source_id,
            ReportSource.owner_id == owner_id,
            ReportSource.report_id == report_id,
        )
    )
    if source is None:
        raise ConcurrencyConflict("analysis source is stale")
    objectives = list(
        (
            await session.scalars(
                select(DraftObjective)
                .where(
                    DraftObjective.draft_id == draft.id,
                    DraftObjective.owner_id == owner_id,
                    DraftObjective.report_id == report_id,
                )
                .order_by(DraftObjective.ordinal)
                .limit(MAX_OBJECTIVES + 1)
            )
        ).all()
    )
    if len(objectives) > MAX_OBJECTIVES or any(
        len(item.content) > MAX_OBJECTIVE_CHARS for item in objectives
    ):
        raise ContextBudgetExceeded
    metric_rows = list(
        (
            await session.scalars(
                select(MetricResult)
                .where(
                    MetricResult.result_set_id == result_set.id,
                    MetricResult.owner_id == owner_id,
                    MetricResult.report_id == report_id,
                )
                .order_by(
                    MetricResult.scope,
                    MetricResult.group_identity,
                    MetricResult.currency,
                    MetricResult.metric_name,
                    MetricResult.id,
                )
                .limit(MAX_METRICS + 1)
            )
        ).all()
    )
    if len(metric_rows) > MAX_METRICS:
        raise ContextBudgetExceeded
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
    metrics = []
    for row in metric_rows:
        inputs = list(
            (
                await session.scalars(
                    select(MetricResultInput)
                    .where(
                        MetricResultInput.metric_result_id == row.id,
                        MetricResultInput.owner_id == owner_id,
                        MetricResultInput.report_id == report_id,
                    )
                    .order_by(MetricResultInput.ordinal)
                )
            ).all()
        )
        represented = list(
            (
                await session.scalars(
                    select(MetricResultCurrency.currency)
                    .where(
                        MetricResultCurrency.metric_result_id == row.id,
                        MetricResultCurrency.owner_id == owner_id,
                        MetricResultCurrency.report_id == report_id,
                    )
                    .order_by(MetricResultCurrency.currency)
                )
            ).all()
        )
        if row.period_start != report.period_start or row.period_end != report.period_end:
            raise ConcurrencyConflict("analysis metric period is stale")
        metrics.append(
            PreparedMetric(
                id=row.id,
                name=cast(Literal["ctr", "cpc", "cpm", "cpl"], row.metric_name),
                availability=cast(Literal["available", "unavailable"], row.availability),
                value=exact(row.value) if row.value is not None else None,
                unit=row.unit,
                unavailable_reason=row.unavailable_reason,
                supporting_field=row.supporting_field,
                scope=cast(Literal["report", "currency", "campaign"], row.scope),
                group_identity=row.group_identity,
                campaign_name=row.campaign_name,
                period=Period(start=row.period_start, end=row.period_end),
                currency=row.currency,
                represented_currencies=represented,
                inputs=[
                    ExactTotal(ordinal=i.ordinal, name=i.input_name, value=exact(i.exact_total))
                    for i in inputs
                ],
                calculation_version=result_set.calculation_version,
                result_set_id=result_set.id,
                numeric_source_identity=result_set.identity.hex(),
            )
        )
    context = PreparedContext(
        version="analysis-context-v1",
        owner_id=owner_id,
        report_id=report_id,
        job_id=job.id,
        source_id=source.id,
        source_checksum_sha256=source.checksum_sha256.hex(),
        confirmation_id=dataset.confirmation_id,
        dataset_id=dataset.id,
        canonical_data_identity=dataset.canonical_data_identity.hex(),
        result_set_id=result_set.id,
        numeric_source_identity=result_set.identity.hex(),
        semantic_input_identity=identity.hex(),
        draft_id=draft.id,
        draft_revision=draft.revision,
        objectives_revision=draft.objectives_revision,
        period=Period(start=report.period_start, end=report.period_end),
        represented_currencies=currencies,
        objectives=[Objective(ordinal=o.ordinal, content=o.content) for o in objectives],
        metrics=metrics,
    )
    if len(context.model_dump_json().encode()) > MAX_CONTEXT_BYTES:
        raise ContextBudgetExceeded
    return context
