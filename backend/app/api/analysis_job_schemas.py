"""Public analysis-job contracts; no provider or broker payloads."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictInt

from app.api.report_schemas import Page, StrictModel


class CreateAnalysisJobRequest(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    dataset_id: UUID | None = None
    metric_result_set_id: UUID | None = None


class RetryAnalysisJobRequest(StrictModel):
    expected_attempt_count: StrictInt = Field(ge=1)


class JobFailure(StrictModel):
    code: str
    message: str
    retryable: bool


class AnalysisAttemptDetail(StrictModel):
    ordinal: int
    state: Literal["queued", "running", "succeeded", "failed"]
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    failure: JobFailure | None


class AnalysisJobSummary(StrictModel):
    id: UUID
    report_id: UUID
    state: Literal["queued", "running", "succeeded", "failed"]
    attempt_count: int
    created_at: datetime
    updated_at: datetime
    failure: JobFailure | None


class AnalysisResultItemPublic(StrictModel):
    section: Literal["summary", "findings", "anomalies", "recommendations", "data_gaps"]
    ordinal: int
    classification: Literal["observation", "hypothesis", "user_claim"]
    content: str


class AnalysisResultPublic(StrictModel):
    id: UUID
    model_identifier: str
    prompt_version: str
    request_provenance: str
    created_at: datetime
    summary: list[AnalysisResultItemPublic]
    findings: list[AnalysisResultItemPublic]
    anomalies: list[AnalysisResultItemPublic]
    recommendations: list[AnalysisResultItemPublic]
    data_gaps: list[AnalysisResultItemPublic]


class AnalysisJobDetail(AnalysisJobSummary):
    dataset_id: UUID
    metric_result_set_id: UUID
    draft_id: UUID
    draft_revision: int
    attempts: list[AnalysisAttemptDetail]
    result_id: UUID | None
    result: AnalysisResultPublic | None = None


class AnalysisJobEnvelope(StrictModel):
    data: AnalysisJobDetail


class AnalysisJobListEnvelope(StrictModel):
    data: list[AnalysisJobSummary]
    page: Page
