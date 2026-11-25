"""Analysis execution with durable claims and sanitized terminal outcomes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from openai import AsyncOpenAI
from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.context import ContextBudgetExceeded, PreparedContext, prepare_context
from app.ai.errors import AnalysisExecutionFailure
from app.ai.openai_adapter import OpenAIAnalysisAdapter, OpenAIClient
from app.ai.output import SECTIONS, RunnerOutput, validate_output
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
    class DatabaseSettings(BaseSettings):
        model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)
        database_url: SecretStr = Field(validation_alias="DATABASE_URL")

    database = DatabaseSettings()

    async def run() -> None:
        engine = create_async_engine(database.database_url.get_secret_value())
        try:

            async def production_runner(context: PreparedContext) -> RunnerOutput:
                try:
                    settings = Settings()
                except ValidationError as error:
                    raise AnalysisExecutionFailure(
                        "provider_unavailable", retryable=False
                    ) from error
                client = AsyncOpenAI(
                    api_key=settings.openai_api_key.get_secret_value(),
                    timeout=settings.openai_timeout_seconds,
                    max_retries=0,
                )
                try:
                    return await OpenAIAnalysisAdapter(settings, cast(OpenAIClient, client))(
                        context
                    )
                finally:
                    await client.close()

            await execute_analysis(
                create_session_factory(engine),
                UUID(owner_id),
                UUID(report_id),
                UUID(job_id),
                ordinal,
                runner=production_runner,
            )
        finally:
            await engine.dispose()

    asyncio.run(run())
