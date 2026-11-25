"""Public confirmed dataset and KPI read contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.api.report_schemas import StrictModel


class DatasetDetail(StrictModel):
    id: UUID
    report_id: UUID
    source_id: UUID
    confirmation_id: UUID
    canonical_data_identity: str
    normalization_policy_version: str
    period_start: date
    period_end: date
    total_records: int
    accepted_row_count: int
    rejected_row_count: int
    row_count_explanation: str
    currencies: list[str]
    metric_result_set_id: UUID | None


class DatasetEnvelope(StrictModel):
    data: DatasetDetail


class CanonicalRowDetail(StrictModel):
    id: UUID
    source_record_index: int
    date: date
    campaign_name: str
    currency: str
    impressions: int | None
    clicks: int | None
    spend: str | None
    leads: int | None


class CanonicalRowsEnvelope(StrictModel):
    data: list[CanonicalRowDetail]
    next_offset: int | None
    total_records: int


class MetricBase(StrictModel):
    id: UUID
    metric_name: Literal["ctr", "cpc", "cpm", "cpl"]
    scope: Literal["report", "campaign", "currency"]
    group_identity: str
    campaign_name: str | None
    currency: str | None
    represented_currencies: list[str]
    period_start: date
    period_end: date
    canonical_data_identity: str
    calculation_version: str
    calculated_at: datetime
    inputs: dict[str, str]


class AvailableMetric(MetricBase):
    availability: Literal["available"]
    value: str
    unit: str


class UnavailableMetric(MetricBase):
    availability: Literal["unavailable"]
    unavailable_reason: Literal[
        "missing_input",
        "zero_denominator",
        "invalid_input",
        "incompatible_currency",
        "incomparable_period",
    ]
    supporting_field: str | None


MetricDetail = Annotated[AvailableMetric | UnavailableMetric, Field(discriminator="availability")]


class MetricsEnvelope(StrictModel):
    data: list[MetricDetail]
    result_set_id: UUID
