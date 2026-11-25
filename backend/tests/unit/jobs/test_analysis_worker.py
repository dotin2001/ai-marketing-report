from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.ai import context as context_module
from app.ai.context import PreparedContext, prepare_context
from app.ai.output import NarrativeItem, NumericAssertion, StructuredOutput
from app.db.models import (
    AnalysisItemMetricReference,
    AnalysisJob,
    AnalysisJobAttempt,
    AnalysisResult,
    DraftObjective,
    Report,
    ReportDraft,
)
from app.db.repositories import ConcurrencyConflict
from app.domain.analysis_jobs import AnalysisJobServices, current_analysis_input
from app.jobs.analysis_worker import (
    AnalysisExecutionFailure,
    RunnerOutput,
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
    sessions, owner, report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "worker-success"
    )

    async def runner(_context: PreparedContext) -> RunnerOutput:
        return RunnerOutput(
            model_identifier="test-model",
            prompt_version="v1",
            request_provenance="fixed-test",
            response=StructuredOutput(
                summary=[
                    NarrativeItem(
                        ordinal=1,
                        classification="observation",
                        content="Observed result.",
                    )
                ],
                findings=[],
                anomalies=[],
                recommendations=[],
                data_gaps=[],
            ),
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

    async def runner(_context: PreparedContext) -> RunnerOutput:
        raise AnalysisExecutionFailure("provider_refusal", retryable=False)

    assert await execute_analysis(sessions, owner, report, job_id, 1, runner)
    assert not await execute_analysis(sessions, owner, report, job_id, 1, runner)
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.failure_code == "provider_refusal"
        assert job.failure_retryable is False


@pytest.mark.asyncio
async def test_mismatched_numeric_provenance_is_rejected(concurrent_engine: AsyncEngine) -> None:
    sessions, owner, report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "worker-provenance"
    )

    async def runner(_context: PreparedContext) -> dict[str, object]:
        return {
            "model_identifier": "test-model",
            "prompt_version": "v1",
            "request_provenance": "fixed-test",
            "response": {
                "summary": [
                    {
                        "ordinal": 1,
                        "classification": "observation",
                        "content": "Untrusted figure 42.",
                    }
                ],
                "findings": [],
                "anomalies": [],
                "recommendations": [],
                "data_gaps": [],
            },
        }

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


@pytest.mark.asyncio
async def test_prepared_context_is_owner_scoped_and_repeatable(
    concurrent_engine: AsyncEngine,
) -> None:
    sessions, owner, report, job_id, semantic, numeric = await seeded(
        concurrent_engine, "prepared-context"
    )
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None
        first = await prepare_context(session, job)
        second = await prepare_context(session, job)
        assert first == second
        assert first.owner_id == owner and first.report_id == report
        assert first.semantic_input_identity == semantic.hex()
        assert first.numeric_source_identity == numeric.hex()
        assert first.objectives[0].content == "Explain acquisition performance"
        assert first.period.start.isoformat() == "2026-01-01"
        assert first.metrics[0].value == "0"
        assert first.metrics[0].inputs[0].value == "0"
        assert first.metrics[0].represented_currencies == ["USD"]
        session.expunge(job)
        foreign_owner = UUID(int=owner.int ^ 1)
        job.owner_id = foreign_owner
        with pytest.raises(ConcurrencyConflict):
            await prepare_context(session, job)
        job.owner_id = owner
        job.metric_result_set_id = UUID(int=job.metric_result_set_id.int ^ 1)
        with pytest.raises(ConcurrencyConflict):
            await prepare_context(session, job)


@pytest.mark.asyncio
async def test_stale_objectives_fail_without_result(concurrent_engine: AsyncEngine) -> None:
    sessions, owner, report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "stale-objectives"
    )
    async with sessions.begin() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None
        await session.execute(
            update(ReportDraft)
            .where(ReportDraft.id == job.draft_id)
            .values(
                revision=2,
                objectives_revision=2,
            )
        )
        await session.execute(
            update(DraftObjective)
            .where(
                DraftObjective.draft_id == job.draft_id,
            )
            .values(content="Changed objective")
        )
    called = False

    async def runner(_context: PreparedContext) -> RunnerOutput:
        nonlocal called
        called = True
        raise AssertionError("stale input reached runner")

    assert await execute_analysis(sessions, owner, report, job_id, 1, runner)
    assert not called
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.failure_code == "stale_result"
        assert job.failure_retryable is False
        assert (
            await session.scalars(
                select(AnalysisResult).where(
                    AnalysisResult.job_id == job_id,
                )
            )
        ).all() == []


@pytest.mark.asyncio
async def test_changed_period_fails_before_runner(concurrent_engine: AsyncEngine) -> None:
    sessions, owner, report_id, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "changed-period"
    )
    async with sessions.begin() as session:
        report = await session.get(Report, report_id)
        assert report is not None
        report.period_start = report.period_start.replace(day=2)
        report.period_revision += 1

    async def runner(_context: PreparedContext) -> RunnerOutput:
        raise AssertionError("changed period reached runner")

    assert await execute_analysis(sessions, owner, report_id, job_id, 1, runner)
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.failure_code == "stale_result"
        assert job.failure_retryable is False


@pytest.mark.asyncio
async def test_grounded_metric_links_are_atomic_and_idempotent(
    concurrent_engine: AsyncEngine,
) -> None:
    sessions, owner, report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "metric-links"
    )

    async def runner(context: PreparedContext) -> RunnerOutput:
        metric = context.metrics[0]
        return RunnerOutput(
            model_identifier="fake",
            prompt_version="v1",
            request_provenance="test",
            response=StructuredOutput(
                summary=[
                    NarrativeItem(
                        ordinal=1,
                        classification="observation",
                        content="Performance was stable.",
                        metric_ids=[metric.id],
                        numeric_assertions=[
                            NumericAssertion(
                                metric_id=metric.id,
                                value=metric.value or "",
                                unit=metric.unit or "",
                                scope=metric.scope,
                                period=metric.period,
                                currency=metric.currency,
                            )
                        ],
                    )
                ],
                findings=[],
                anomalies=[],
                recommendations=[],
                data_gaps=[],
            ),
        )

    assert await execute_analysis(sessions, owner, report, job_id, 1, runner)
    assert not await execute_analysis(sessions, owner, report, job_id, 1, runner)
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.state == "succeeded", job.failure_code if job else None
        links = (
            await session.scalars(
                select(AnalysisItemMetricReference).where(
                    AnalysisItemMetricReference.report_id == report,
                )
            )
        ).all()
        assert len(links) == 1
        assert links[0].owner_id == owner
        assert links[0].metric_result_id is not None


@pytest.mark.asyncio
async def test_context_budget_fails_safely(concurrent_engine: AsyncEngine) -> None:
    sessions, owner, report_id, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "budget"
    )
    async with sessions.begin() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None
        objective = await session.scalar(
            select(DraftObjective).where(
                DraftObjective.draft_id == job.draft_id,
            )
        )
        assert objective is not None
        objective.content = "x" * 1001
        report = await session.scalar(select(Report).where(Report.id == report_id))
        assert report is not None
        _draft, _dataset, _metrics, identity = await current_analysis_input(
            session, report, job.draft_revision, job.dataset_id, job.metric_result_set_id
        )
        job.semantic_input_identity = identity
    assert await execute_analysis(sessions, owner, report_id, job_id, 1)
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.failure_code == "provider_unavailable"
        assert job.failure_retryable is False
        assert job.failure_message == "Analysis could not be completed."


@pytest.mark.asyncio
async def test_context_budget_boundaries(
    concurrent_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions, _owner, _report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "budget-boundaries"
    )
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None
        prepared = await prepare_context(session, job)
        exact_bytes = len(prepared.model_dump_json().encode())
        monkeypatch.setattr(context_module, "MAX_CONTEXT_BYTES", exact_bytes)
        assert await prepare_context(session, job) == prepared
        monkeypatch.setattr(context_module, "MAX_CONTEXT_BYTES", exact_bytes - 1)
        with pytest.raises(context_module.ContextBudgetExceeded):
            await prepare_context(session, job)
        monkeypatch.setattr(context_module, "MAX_CONTEXT_BYTES", exact_bytes)
        monkeypatch.setattr(context_module, "MAX_METRICS", 1)
        assert await prepare_context(session, job) == prepared
        monkeypatch.setattr(context_module, "MAX_METRICS", 0)
        with pytest.raises(context_module.ContextBudgetExceeded):
            await prepare_context(session, job)


@pytest.mark.asyncio
async def test_foreign_metric_reference_rolls_back_and_is_sanitized(
    concurrent_engine: AsyncEngine,
) -> None:
    sessions, owner, report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "foreign-reference"
    )

    async def runner(_context: PreparedContext) -> RunnerOutput:
        return RunnerOutput(
            model_identifier="fake",
            prompt_version="v1",
            request_provenance="test",
            response=StructuredOutput(
                summary=[
                    NarrativeItem(
                        ordinal=1,
                        classification="observation",
                        content="Source text was ignored.",
                        metric_ids=[uuid4()],
                    )
                ],
                findings=[],
                anomalies=[],
                recommendations=[],
                data_gaps=[],
            ),
        )

    assert await execute_analysis(sessions, owner, report, job_id, 1, runner)
    async with sessions() as session:
        assert (
            await session.scalars(
                select(AnalysisResult).where(
                    AnalysisResult.job_id == job_id,
                )
            )
        ).all() == []
        assert (
            await session.scalars(
                select(AnalysisItemMetricReference).where(
                    AnalysisItemMetricReference.report_id == report,
                )
            )
        ).all() == []
    detail = await AnalysisJobServices(sessions, "s" * 32).detail(owner, report, job_id)
    assert detail.result is None
    assert detail.failure is not None
    assert detail.failure.code == "invalid_structured_output"
    assert detail.failure.message == "Analysis could not be completed."
