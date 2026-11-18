"""Public report request and response contracts."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_serializer,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Period(StrictModel):
    start_date: date
    end_date: date

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def iso_date_only(cls, value: Any) -> Any:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
            raise ValueError("Enter a date in YYYY-MM-DD format.")
        return value

    @model_validator(mode="after")
    def inclusive(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("End date must not precede start date.")
        return self


class ReportName(StrictModel):
    name: StrictStr

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not 1 <= len(trimmed) <= 200:
            raise ValueError("Name must contain 1 to 200 characters.")
        return trimmed


def _objective(value: str) -> str:
    trimmed = value.strip()
    if not 1 <= len(trimmed) <= 2000:
        raise ValueError("Objective must contain 1 to 2000 characters.")
    return trimmed


class ObjectiveList(StrictModel):
    objectives: list[Annotated[StrictStr, AfterValidator(_objective)]] = Field(
        min_length=1, max_length=20
    )


class CreateReportRequest(ReportName, ObjectiveList):
    period: Period


class MetadataPatchRequest(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    name: StrictStr | None = None
    period: Period | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return ReportName(name=value).name if value is not None else None

    @model_validator(mode="after")
    def require_edit(self) -> Self:
        if self.name is None and self.period is None:
            raise ValueError("Provide a name or period.")
        return self


class ObjectivesPatchRequest(ObjectiveList):
    expected_revision: StrictInt = Field(ge=1)


class ListReportsQuery(StrictModel):
    limit: StrictInt = Field(default=25, ge=1, le=100)
    cursor: str | None = None


class PublicModel(StrictModel):
    @field_serializer("created_at", "updated_at", check_fields=False)
    def utc_instant(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class DraftReference(StrictModel):
    id: UUID
    revision: int


class VersionReference(StrictModel):
    id: UUID
    version_number: int


class NarrativeItem(StrictModel):
    id: UUID
    section: str
    ordinal: int
    content: str
    classification: str | None


class Claim(StrictModel):
    id: UUID
    ordinal: int
    content: str
    classification: str
    source_id: UUID | None


class Limitation(StrictModel):
    id: UUID
    ordinal: int
    content: str


class DraftDetail(PublicModel):
    id: UUID
    report_id: UUID
    revision: int
    objectives: list[str]
    narrative: list[NarrativeItem] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    limitations: list[Limitation] = Field(default_factory=list)
    current_metric_result_set_id: UUID | None
    current_analysis_result_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ReportSummary(PublicModel):
    id: UUID
    name: str
    period: Period
    stage: str
    active_draft: DraftReference
    current_source_id: UUID | None
    current_dataset_id: UUID | None
    current_analysis_result_id: UUID | None
    latest_version: VersionReference | None
    created_at: datetime
    updated_at: datetime


class ReportDetail(ReportSummary):
    objectives: list[str]
    active_draft: DraftDetail  # type: ignore[assignment]
    current_metric_result_set_id: UUID | None


class Page(StrictModel):
    limit: int
    has_more: bool
    next_cursor: str | None


class ReportEnvelope(StrictModel):
    data: ReportDetail


class DraftEnvelope(StrictModel):
    data: DraftDetail


class ReportListEnvelope(StrictModel):
    data: list[ReportSummary]
    page: Page


class ErrorDetail(StrictModel):
    code: str
    message: str
    path: list[str | int]


class ErrorBody(StrictModel):
    code: str
    message: str
    request_id: str
    retryable: bool
    details: list[ErrorDetail]
    context: dict[str, str | int]


class ErrorEnvelope(StrictModel):
    error: ErrorBody
