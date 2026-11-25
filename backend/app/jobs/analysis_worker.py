"""Analysis execution with durable claims and sanitized terminal outcomes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.models import AnalysisJob, AnalysisResult, AnalysisResultItem, MetricResultSet
from app.db.repositories import (
    ConcurrencyConflict,
    claim_analysis_job,
    fail_analysis_job,
    finish_analysis_job,
    stale_running_analysis_attempts,
)
from app.db.session import create_session_factory, transaction
from app.jobs.celery_app import celery_app

SAFE_FAILURES = frozenset(
    {
        "provider_timeout",
        "provider_refusal",
        "provider_unavailable",
        "incomplete_response",
        "invalid_structured_output",
        "stale_result",
    }
)


class AnalysisExecutionFailure(Exception):
    def __init__(self, code: str, retryable: bool = True) -> None:
        if code not in SAFE_FAILURES:
            raise ValueError("unsupported analysis failure")
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class AnalysisItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: Literal["summary", "findings", "anomalies", "recommendations", "data_gaps"]
    ordinal: int = Field(ge=1)
    classification: Literal["observation", "hypothesis", "user_claim"]
    content: str = Field(min_length=1)


class AnalysisExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_identifier: str = Field(min_length=1, max_length=255)
    prompt_version: str = Field(min_length=1, max_length=64)
    request_provenance: str = Field(min_length=1, max_length=500)
    semantic_input_identity: bytes = Field(min_length=32, max_length=32)
    numeric_source_identity: bytes = Field(min_length=32, max_length=32)
    items: list[AnalysisItem] = Field(min_length=1)


AnalysisRunner = Callable[[AsyncSession, AnalysisJob], Awaitable[AnalysisExecutionResult]]


async def unavailable_executor(
    _session: AsyncSession, _job: AnalysisJob
) -> AnalysisExecutionResult:
    raise AnalysisExecutionFailure("provider_unavailable")


async def execute_analysis(
    sessions: async_sessionmaker[AsyncSession],
    owner_id: UUID,
    report_id: UUID,
    job_id: UUID,
    ordinal: int,
    runner: AnalysisRunner = unavailable_executor,
) -> bool:
    async with transaction(sessions) as session:
        claimed = await claim_analysis_job(
            session,
            owner_id=owner_id,
            report_id=report_id,
            job_id=job_id,
            expected_attempt_count=ordinal,
        )
    if not claimed:
        return False
    try:
        async with sessions() as session:
            job = await session.scalar(
                select(AnalysisJob).where(
                    AnalysisJob.id == job_id,
                    AnalysisJob.owner_id == owner_id,
                    AnalysisJob.report_id == report_id,
                )
            )
            if job is None:
                raise AnalysisExecutionFailure("stale_result", retryable=False)
            execution = AnalysisExecutionResult.model_validate(await runner(session, job))
            numeric_identity = await session.scalar(
                select(MetricResultSet.identity).where(
                    MetricResultSet.id == job.metric_result_set_id,
                    MetricResultSet.owner_id == owner_id,
                    MetricResultSet.report_id == report_id,
                )
            )
            if (
                execution.semantic_input_identity != job.semantic_input_identity
                or execution.numeric_source_identity != numeric_identity
            ):
                raise AnalysisExecutionFailure("invalid_structured_output", retryable=False)
        result = AnalysisResult(
            owner_id=owner_id,
            report_id=report_id,
            job_id=job_id,
            semantic_input_identity=execution.semantic_input_identity,
            numeric_source_identity=execution.numeric_source_identity,
            model_identifier=execution.model_identifier,
            prompt_version=execution.prompt_version,
            request_provenance=execution.request_provenance,
        )
        items = [
            AnalysisResultItem(
                owner_id=owner_id,
                report_id=report_id,
                result_id=result.id,
                section=item.section,
                ordinal=item.ordinal,
                classification=item.classification,
                content=item.content,
            )
            for item in execution.items
        ]
        async with transaction(sessions) as session:
            await finish_analysis_job(
                session,
                owner_id=owner_id,
                report_id=report_id,
                job_id=job_id,
                expected_attempt_count=ordinal,
                result=result,
                items=items,
            )
    except ConcurrencyConflict:
        return False
    except Exception as error:
        if isinstance(error, AnalysisExecutionFailure):
            code, retryable = error.code, error.retryable
        else:
            code, retryable = "provider_unavailable", True
        try:
            async with transaction(sessions) as session:
                await fail_analysis_job(
                    session,
                    owner_id=owner_id,
                    report_id=report_id,
                    job_id=job_id,
                    expected_attempt_count=ordinal,
                    failure_code=code,
                    failure_message="Analysis could not be completed.",
                    retryable=retryable,
                )
        except ConcurrencyConflict:
            return False
    return True


async def fail_stale_running(
    sessions: async_sessionmaker[AsyncSession],
    timeout_seconds: int,
    limit: int = 100,
) -> int:
    cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
    async with sessions() as session:
        stale = await stale_running_analysis_attempts(session, before=cutoff, limit=limit)
    failed = 0
    for owner_id, report_id, job_id, ordinal in stale:
        try:
            async with transaction(sessions) as session:
                await fail_analysis_job(
                    session,
                    owner_id=owner_id,
                    report_id=report_id,
                    job_id=job_id,
                    expected_attempt_count=ordinal,
                    failure_code="provider_timeout",
                    failure_message="Analysis timed out.",
                    retryable=True,
                )
            failed += 1
        except ConcurrencyConflict:
            pass
    return failed


@celery_app.task(name="analysis.execute", ignore_result=True)  # type: ignore[misc]
def analysis_task(owner_id: str, report_id: str, job_id: str, ordinal: int) -> None:
    settings = Settings()

    async def run() -> None:
        engine = create_async_engine(settings.database_url.get_secret_value())
        try:
            await execute_analysis(
                create_session_factory(engine),
                UUID(owner_id),
                UUID(report_id),
                UUID(job_id),
                ordinal,
            )
        finally:
            await engine.dispose()

    asyncio.run(run())
