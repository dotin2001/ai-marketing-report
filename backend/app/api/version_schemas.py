"""Public contracts for immutable report versions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictInt

from app.api.report_schemas import DraftDetail, Page, PublicModel, StrictModel
from app.db.snapshots import ReportVersionSnapshot, ReportVersionSnapshotV2


class CreateVersionRequest(StrictModel):
    expected_draft_revision: StrictInt = Field(ge=1)


class RestoreVersionRequest(StrictModel):
    expected_draft_id: UUID
    expected_draft_revision: StrictInt = Field(ge=1)


class ListVersionsQuery(StrictModel):
    limit: StrictInt = Field(default=25, ge=1, le=100)
    cursor: str | None = None


class CreatePdfExportRequest(StrictModel):
    template_version: Literal["report-v1"]


class RetryPdfExportRequest(StrictModel):
    input_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_attempt_count: StrictInt = Field(ge=1)


class PdfExportFailure(StrictModel):
    code: str
    message: str
    retryable: bool


class PdfExportAttemptDetail(StrictModel):
    ordinal: int
    state: Literal["queued", "running", "succeeded", "failed"]
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    failure: PdfExportFailure | None


class PdfExportFile(StrictModel):
    filename: str
    content_type: Literal["application/pdf"]
    byte_size: int = Field(gt=0)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    download_available: bool


class PdfExportSummary(PublicModel):
    id: UUID
    report_id: UUID
    version_id: UUID
    template_version: str
    input_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["queued", "running", "succeeded", "failed"]
    attempt_count: int
    created_at: datetime
    updated_at: datetime
    failure: PdfExportFailure | None = None


class PdfExportDetail(PdfExportSummary):
    attempts: list[PdfExportAttemptDetail]
    file: PdfExportFile | None


class PdfExportEnvelope(StrictModel):
    data: PdfExportDetail


class PdfExportListEnvelope(StrictModel):
    data: list[PdfExportSummary]
    page: Page


class VersionSummary(PublicModel):
    id: UUID
    report_id: UUID
    version_number: int
    source_draft_id: UUID
    source_draft_revision: int
    template_version: str
    snapshot_schema_version: int
    snapshot_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_id: UUID | None
    metric_result_set_id: UUID | None
    analysis_result_id: UUID | None
    latest_pdf_export: PdfExportSummary | None
    created_at: datetime


class VersionDetail(VersionSummary):
    snapshot: ReportVersionSnapshotV2 | ReportVersionSnapshot


class VersionEnvelope(StrictModel):
    data: VersionDetail


class VersionListEnvelope(StrictModel):
    data: list[VersionSummary]
    page: Page


class RestoredDraftEnvelope(StrictModel):
    data: DraftDetail
