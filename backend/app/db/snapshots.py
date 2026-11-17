"""Versioned, public-safe report snapshot validation."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORBIDDEN_SNAPSHOT_KEYS = frozenset(
    {
        "inline_text",
        "object_key",
        "public_url",
        "signed_url",
        "credential",
        "password",
        "access_key",
        "secret_key",
        "api_key",
        "raw_prompt",
        "request_prompt",
    }
)
ExactDecimal = Annotated[str, Field(pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")]


def _reject_forbidden_keys(value: Any) -> Any:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_SNAPSHOT_KEYS.intersection(str(key).lower() for key in value)
        if forbidden:
            raise ValueError("snapshot contains a forbidden private field")
        for nested in value.values():
            _reject_forbidden_keys(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_forbidden_keys(nested)
    return value


class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="before")
    @classmethod
    def reject_private_fields(cls, value: Any) -> Any:
        return _reject_forbidden_keys(value)


class SourceSnapshot(SnapshotModel):
    source_id: UUID
    source_type: Literal["text", "csv"]
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)
    media_type: str = Field(min_length=1, max_length=255)
    display_filename: str | None = None


class MappingSnapshot(SnapshotModel):
    source_column_ordinal: int = Field(ge=0)
    canonical_field: Literal[
        "date", "campaign_name", "currency", "impressions", "clicks", "spend", "leads"
    ]


class ConfirmedImportSnapshot(SnapshotModel):
    confirmation_id: UUID
    configuration_id: UUID
    configuration_revision: int = Field(gt=0)
    normalization_policy_version: str = Field(min_length=1, max_length=64)
    date_format: str | None = Field(default=None, max_length=64)
    mappings: tuple[MappingSnapshot, ...]
    validation_id: UUID
    warning_codes: tuple[Annotated[str, Field(min_length=1, max_length=64)], ...] = ()
    canonical_data_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(gt=0)
    currencies: tuple[Annotated[str, Field(pattern=r"^[A-Z]{3}$")], ...]

    @model_validator(mode="after")
    def mappings_are_complete_and_unique(self) -> ConfirmedImportSnapshot:
        ordinals = [mapping.source_column_ordinal for mapping in self.mappings]
        fields = [mapping.canonical_field for mapping in self.mappings]
        if len(ordinals) != len(set(ordinals)) or len(fields) != len(set(fields)):
            raise ValueError("confirmed import mappings must be unique")
        if not {"date", "campaign_name", "currency"}.issubset(fields):
            raise ValueError("confirmed import is missing required dimensions")
        if not {"impressions", "clicks", "spend", "leads"}.intersection(fields):
            raise ValueError("confirmed import is missing a measure")
        if not self.currencies or len(self.currencies) != len(set(self.currencies)):
            raise ValueError("confirmed import currencies must be non-empty and unique")
        return self


class MetricSnapshot(SnapshotModel):
    metric_result_id: UUID
    name: Literal["ctr", "cpc", "cpm", "cpl"]
    availability: Literal["available", "unavailable"]
    value: ExactDecimal | None = None
    unit: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    unavailable_reason: (
        Literal[
            "missing_input",
            "zero_denominator",
            "invalid_input",
            "incompatible_currency",
            "incomparable_period",
        ]
        | None
    ) = None
    exact_inputs: dict[Annotated[str, Field(min_length=1, max_length=32)], ExactDecimal]
    represented_currencies: tuple[Annotated[str, Field(pattern=r"^[A-Z]{3}$")], ...] = ()
    scope: Annotated[str, Field(min_length=1, max_length=64)]
    period_start: date
    period_end: date
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    calculation_version: Annotated[str, Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def availability_fields_match(self) -> MetricSnapshot:
        if self.period_end < self.period_start:
            raise ValueError("metric period is reversed")
        if self.availability == "available":
            if self.value is None or self.unit is None or self.unavailable_reason is not None:
                raise ValueError("available metric fields conflict")
        elif self.value is not None or self.unit is not None or self.unavailable_reason is None:
            raise ValueError("unavailable metric fields conflict")
        if len(self.represented_currencies) != len(set(self.represented_currencies)):
            raise ValueError("metric currencies must be unique")
        return self


class AnalysisItemSnapshot(SnapshotModel):
    section: Literal["summary", "findings", "anomalies", "recommendations", "data_gaps"]
    ordinal: int = Field(gt=0)
    classification: Literal["observation", "hypothesis", "user_claim"]
    content: str = Field(min_length=1)
    metric_result_ids: tuple[UUID, ...] = ()
    claim_ids: tuple[UUID, ...] = ()


class AnalysisSnapshot(SnapshotModel):
    result_id: UUID
    model_identifier: str = Field(min_length=1, max_length=255)
    prompt_version: str = Field(min_length=1, max_length=64)
    request_provenance: str = Field(min_length=1, max_length=500)
    semantic_input_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    numeric_source_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    items: tuple[AnalysisItemSnapshot, ...]


class NarrativeSnapshot(SnapshotModel):
    item_id: UUID
    section: Literal["summary", "findings", "anomalies", "recommendations", "data_gaps"]
    ordinal: int = Field(gt=0)
    classification: Literal["observation", "hypothesis", "user_claim"] | None = None
    content: str = Field(min_length=1)


class ClaimSnapshot(SnapshotModel):
    claim_id: UUID
    ordinal: int = Field(gt=0)
    classification: Literal["user_claim"] = "user_claim"
    content: str = Field(min_length=1)
    source_id: UUID | None = None


class ChartSnapshot(SnapshotModel):
    chart_type: Literal["bar", "line", "table"]
    title: str = Field(min_length=1, max_length=160)
    x_label: str | None = Field(default=None, max_length=80)
    y_label: str | None = Field(default=None, max_length=80)
    scope: str = Field(min_length=1, max_length=64)
    metric_result_ids: tuple[UUID, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def valid_references(self) -> ChartSnapshot:
        if not self.title.strip() or not self.scope.strip():
            raise ValueError("chart title and scope must not be blank")
        if len(self.metric_result_ids) != len(set(self.metric_result_ids)):
            raise ValueError("chart metric references must be unique")
        return self


class ReportVersionSnapshot(SnapshotModel):
    schema_version: Literal[1, 2] = 1
    report_id: UUID
    report_name: str = Field(min_length=1, max_length=255)
    period_start: date
    period_end: date
    objectives: tuple[Annotated[str, Field(min_length=1)], ...]
    source: SourceSnapshot
    confirmed_import: ConfirmedImportSnapshot | None = None
    canonical_data_identity: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    metrics: tuple[MetricSnapshot, ...]
    analysis: AnalysisSnapshot | None = None
    narrative: tuple[NarrativeSnapshot, ...]
    limitations: tuple[Annotated[str, Field(min_length=1)], ...]
    claims: tuple[ClaimSnapshot, ...]
    template_version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def reproducibility_fields_are_coherent(self) -> ReportVersionSnapshot:
        if type(self) is ReportVersionSnapshot and self.schema_version != 1:
            raise ValueError("schema 1 snapshot must declare schema version 1")
        if self.period_end < self.period_start:
            raise ValueError("report period is reversed")
        if not self.objectives:
            raise ValueError("snapshot must contain objectives")
        if self.confirmed_import is not None:
            if self.canonical_data_identity != self.confirmed_import.canonical_data_identity:
                raise ValueError("canonical identity does not match confirmed import")
        elif self.canonical_data_identity is not None or self.metrics:
            raise ValueError("canonical data and metrics require a confirmed import")
        return self


class ReportVersionSnapshotV2(ReportVersionSnapshot):
    schema_version: Literal[2] = 2
    dataset_id: UUID | None = None
    metric_result_set_id: UUID | None = None
    analysis_result_id: UUID | None = None
    charts: tuple[ChartSnapshot, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def bindings_are_coherent(self) -> ReportVersionSnapshotV2:
        if self.source.source_type == "csv":
            if self.confirmed_import is None or self.dataset_id is None:
                raise ValueError("structured version requires confirmed import and dataset binding")
            if self.metrics and self.metric_result_set_id is None:
                raise ValueError("structured metrics require a result-set binding")
            if not self.metrics and self.metric_result_set_id is not None:
                raise ValueError("result-set binding requires included metrics")
        elif (
            self.confirmed_import is not None
            or self.dataset_id is not None
            or self.metric_result_set_id is not None
            or self.metrics
        ):
            raise ValueError("text-only version cannot contain structured data or metrics")
        if (self.analysis_result_id is None) != (self.analysis is None):
            raise ValueError("analysis binding and snapshot must agree")
        if self.analysis is not None and self.analysis_result_id != self.analysis.result_id:
            raise ValueError("analysis result identity does not match")
        metric_ids = {metric.metric_result_id for metric in self.metrics}
        if len(metric_ids) != len(self.metrics):
            raise ValueError("metric result identities must be unique")
        if any(not set(chart.metric_result_ids).issubset(metric_ids) for chart in self.charts):
            raise ValueError("chart references a metric absent from the snapshot")
        if self.source.source_type == "text" and (self.charts or self.analysis is not None):
            raise ValueError("text-only version cannot contain charts or structured analysis")
        return self


def parse_report_version_snapshot(value: object) -> ReportVersionSnapshot | ReportVersionSnapshotV2:
    if not isinstance(value, dict):
        raise ValueError("report version snapshot must be an object")
    if value.get("schema_version") == 1:
        return ReportVersionSnapshot.model_validate(value)
    if value.get("schema_version") == 2:
        return ReportVersionSnapshotV2.model_validate(value)
    raise ValueError("unsupported report version snapshot schema")
