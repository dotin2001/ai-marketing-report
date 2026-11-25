from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import AnalysisJob, AnalysisJobAttempt, AnalysisResult
from app.domain.analysis_jobs import AnalysisJobServices
from app.jobs.analysis_worker import (
    AnalysisExecutionFailure,
    AnalysisExecutionResult,
    AnalysisItem,
    execute_analysis,
    fail_stale_running,
)
from tests.integration.db.test_analysis_jobs import seed_analysis_job

pytestmark = pytest.mark.postgres
pytest_plugins = ("tests.integration.db.test_analysis_jobs",)


async def seeded(
    engine: AsyncEngine, subject: str
) -> tuple[async_sessionmaker[AsyncSession], UUID, UUID, UUID, bytes, bytes]:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        report, _dataset, metric_set, _draft, job = await seed_analysis_job(
            session, subject=subject
        )
        await session.commit()
    return (
        sessions,
        report.owner_id,
        report.id,
        job.id,
        job.semantic_input_identity,
        metric_set.identity,
    )


@pytest.mark.asyncio
async def test_validated_completion_and_redelivery(concurrent_engine: AsyncEngine) -> None:
    sessions, owner, report, job_id, semantic, numeric = await seeded(
        concurrent_engine, "worker-success"
    )

    async def runner(_session: AsyncSession, _job: AnalysisJob) -> AnalysisExecutionResult:
        return AnalysisExecutionResult(
            model_identifier="test-model",
            prompt_version="v1",
            request_provenance="fixed-test",
            semantic_input_identity=semantic,
            numeric_source_identity=numeric,
            items=[
                AnalysisItem(
                    section="summary",
                    ordinal=1,
                    classification="observation",
                    content="Observed result.",
                )
            ],
        )

    assert await execute_analysis(sessions, owner, report, job_id, 1, runner)
    assert not await execute_analysis(sessions, owner, report, job_id, 1, runner)
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.state == "succeeded" and job.current_result_id
        results = (
            await session.scalars(select(AnalysisResult).where(AnalysisResult.job_id == job_id))
        ).all()
        assert len(results) == 1
        attempt = await session.scalar(
            select(AnalysisJobAttempt).where(AnalysisJobAttempt.job_id == job_id)
        )
        assert attempt is not None and attempt.started_at and attempt.finished_at
    public = await AnalysisJobServices(sessions, "s" * 32).detail(owner, report, job_id)
    assert public.result is not None
    assert public.result.summary[0].content == "Observed result."
    assert public.result.findings == []


@pytest.mark.asyncio
async def test_executor_unavailable_is_sanitized(concurrent_engine: AsyncEngine) -> None:
    sessions, owner, report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "worker-unavailable"
    )
    assert await execute_analysis(sessions, owner, report, job_id, 1)
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.state == "failed"
        assert job.failure_code == "provider_unavailable" and job.failure_retryable
        assert job.failure_message == "Analysis could not be completed."


@pytest.mark.asyncio
async def test_runner_error_does_not_leak_and_old_ordinal_is_ignored(
    concurrent_engine: AsyncEngine,
) -> None:
    sessions, owner, report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "worker-failure"
    )

    async def runner(_session: AsyncSession, _job: AnalysisJob) -> AnalysisExecutionResult:
        raise AnalysisExecutionFailure("provider_refusal", retryable=False)

    assert await execute_analysis(sessions, owner, report, job_id, 1, runner)
    assert not await execute_analysis(sessions, owner, report, job_id, 1, runner)
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.failure_code == "provider_refusal"
        assert job.failure_retryable is False


@pytest.mark.asyncio
async def test_mismatched_numeric_provenance_is_rejected(concurrent_engine: AsyncEngine) -> None:
    sessions, owner, report, job_id, semantic, _numeric = await seeded(
        concurrent_engine, "worker-provenance"
    )

    async def runner(_session: AsyncSession, _job: AnalysisJob) -> AnalysisExecutionResult:
        return AnalysisExecutionResult(
            model_identifier="test-model",
            prompt_version="v1",
            request_provenance="fixed-test",
            semantic_input_identity=semantic,
            numeric_source_identity=uuid4().bytes + uuid4().bytes,
            items=[
                AnalysisItem(
                    section="summary",
                    ordinal=1,
                    classification="observation",
                    content="Untrusted number.",
                )
            ],
        )

    assert await execute_analysis(sessions, owner, report, job_id, 1, runner)
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.state == "failed"
        assert job.failure_code == "invalid_structured_output"
        assert (
            await session.scalars(select(AnalysisResult).where(AnalysisResult.job_id == job_id))
        ).all() == []


@pytest.mark.asyncio
async def test_reaper_ignores_fresh_attempt(concurrent_engine: AsyncEngine) -> None:
    sessions, _owner, _report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "worker-fresh"
    )
    assert await fail_stale_running(sessions, timeout_seconds=1) == 0
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.state == "queued"
