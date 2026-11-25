"""Analysis execution with durable claims and sanitized terminal outcomes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.context import ContextBudgetExceeded, PreparedContext, prepare_context
from app.ai.output import SECTIONS, StructuredOutput, validate_output
from app.core.config import Settings
from app.db.models import (
    AnalysisItemMetricReference,
    AnalysisJob,
    AnalysisResult,
    AnalysisResultItem,
)
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


class RunnerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_identifier: str = Field(min_length=1, max_length=255)
    prompt_version: str = Field(min_length=1, max_length=64)
    request_provenance: str = Field(min_length=1, max_length=500)
    response: StructuredOutput


AnalysisRunner = Callable[[PreparedContext], Awaitable[RunnerOutput | dict[str, object]]]


async def unavailable_executor(_context: PreparedContext) -> RunnerOutput:
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
            context = await prepare_context(session, job)
        raw = await runner(context)
        try:
            execution = RunnerOutput.model_validate(
                raw.model_dump() if isinstance(raw, RunnerOutput) else raw
            )
            validated = validate_output(
                execution.response,
                context,
                model_identifier=execution.model_identifier,
                prompt_version=execution.prompt_version,
                request_provenance=execution.request_provenance,
            )
        except (ValidationError, ValueError) as error:
            raise AnalysisExecutionFailure("invalid_structured_output", retryable=False) from error
        result = AnalysisResult(
            owner_id=owner_id,
            report_id=report_id,
            job_id=job_id,
            semantic_input_identity=bytes.fromhex(validated.semantic_input_identity),
            numeric_source_identity=bytes.fromhex(validated.numeric_source_identity),
            model_identifier=validated.model_identifier,
            prompt_version=validated.prompt_version,
            request_provenance=validated.request_provenance,
        )
        items: list[AnalysisResultItem] = []
        references: list[AnalysisItemMetricReference] = []
        for section in SECTIONS:
            for item in getattr(validated.sections, section):
                row = AnalysisResultItem(
                    id=uuid4(),
                    owner_id=owner_id,
                    report_id=report_id,
                    result_id=result.id,
                    section=section,
                    ordinal=item.ordinal,
                    classification=item.classification,
                    content=item.content,
                )
                items.append(row)
                references.extend(
                    AnalysisItemMetricReference(
                        item_id=row.id,
                        metric_result_id=metric_id,
                        owner_id=owner_id,
                        report_id=report_id,
                    )
                    for metric_id in item.metric_ids
                )
        async with transaction(sessions) as session:
            current_job = await session.scalar(
                select(AnalysisJob).where(
                    AnalysisJob.id == job_id,
                    AnalysisJob.owner_id == owner_id,
                    AnalysisJob.report_id == report_id,
                )
            )
            if current_job is None:
                raise ConcurrencyConflict("analysis job is stale")
            await prepare_context(session, current_job)
            await finish_analysis_job(
                session,
                owner_id=owner_id,
                report_id=report_id,
                job_id=job_id,
                expected_attempt_count=ordinal,
                result=result,
                items=items,
                metric_references=references,
            )
    except Exception as error:
        if isinstance(error, AnalysisExecutionFailure):
            code, retryable = error.code, error.retryable
        elif isinstance(error, ConcurrencyConflict):
            code, retryable = "stale_result", False
        elif isinstance(error, ContextBudgetExceeded):
            code, retryable = "provider_unavailable", False
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
