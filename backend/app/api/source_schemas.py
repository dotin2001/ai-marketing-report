"""Safe public contracts for unconfirmed source intake and preview."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictInt, StrictStr

from app.api.report_schemas import PublicModel, StrictModel


class PasteSourceRequest(StrictModel):
    content: StrictStr = Field(min_length=1)


class SourceDetail(PublicModel):
    id: UUID
    report_id: UUID
    source_type: Literal["csv", "text"]
    byte_size: int
    checksum_sha256: str
    media_type: str
    encoding: str | None
    original_filename_untrusted: str | None
    display_filename: str | None
    created_at: datetime


class SourceEnvelope(StrictModel):
    data: SourceDetail


class PreviewColumn(StrictModel):
    ordinal: int
    original_header: str


class PreviewRow(StrictModel):
    record_index: int
    values: list[str]


class SourcePreview(StrictModel):
    source_type: Literal["csv", "text"]
    confirmed: Literal[False] = False
    validation_status: Literal["unvalidated"] = "unvalidated"
    columns: list[PreviewColumn] | None = None
    rows: list[PreviewRow] | None = None
    total_records: int | None = None
    excerpt: str | None = None
    truncated: bool


class SourcePreviewEnvelope(StrictModel):
    data: SourcePreview


class ColumnMapping(StrictModel):
    source_column_ordinal: StrictInt = Field(ge=0)
    canonical_field: Literal[
        "date", "campaign_name", "currency", "impressions", "clicks", "spend", "leads"
    ]


class ImportConfigurationRequest(StrictModel):
    expected_revision: StrictInt = Field(ge=0)
    normalization_policy_version: Literal["normalize-v1"]
    date_format: Literal["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"] | None = None
    mappings: list[ColumnMapping] = Field(max_length=7)


class ImportConfigurationDetail(StrictModel):
    id: UUID
    report_id: UUID
    source_id: UUID
    revision: int
    normalization_policy_version: str
    date_format: str | None
    mappings: list[ColumnMapping]
    confirmed: Literal[False] = False


class ImportConfigurationEnvelope(StrictModel):
    data: ImportConfigurationDetail


class ValidateImportRequest(StrictModel):
    expected_revision: StrictInt = Field(ge=1)


class ValidationIssue(StrictModel):
    id: UUID
    code: str
    severity: Literal["error", "warning"]
    message: str
    canonical_field: str | None
    source_column_ordinal: int | None
    source_record_index: int | None
    related_record_index: int | None


class ImportValidationDetail(StrictModel):
    id: UUID
    report_id: UUID
    source_id: UUID
    configuration_id: UUID
    revision: int
    source_checksum_sha256: str
    normalization_policy_version: str
    period_start: date
    period_end: date
    period_revision: int
    total_records: int
    error_count: int
    warning_count: int
    confirmation_blocked: bool
    confirmed: Literal[False] = False
    preview_identity: str | None = None
    issues: list[ValidationIssue]


class ImportValidationEnvelope(StrictModel):
    data: ImportValidationDetail


class ConfirmImportRequest(StrictModel):
    validation_id: UUID
    expected_revision: StrictInt = Field(ge=1)
    acknowledged_warning_ids: list[UUID] = Field(default_factory=list)


class ConfirmedImportDetail(StrictModel):
    id: UUID
    report_id: UUID
    source_id: UUID
    validation_id: UUID
    configuration_id: UUID
    revision: int
    confirmed_by: UUID
    dataset_id: UUID
    canonical_data_identity: str
    source_checksum_sha256: str
    normalization_policy_version: str
    period_start: date
    period_end: date
    period_revision: int
    row_count: int
    currencies: list[str]
    mappings: list[ColumnMapping]


class ConfirmedImportEnvelope(StrictModel):
    data: ConfirmedImportDetail
