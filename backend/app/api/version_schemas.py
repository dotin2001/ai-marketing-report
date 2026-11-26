"""Public contracts for immutable report versions."""

from __future__ import annotations

from datetime import datetime
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


class PdfExportSummary(PublicModel):
    id: UUID
    report_id: UUID
    version_id: UUID
    template_version: str
    input_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: str
    attempt_count: int
    created_at: datetime
    updated_at: datetime


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
