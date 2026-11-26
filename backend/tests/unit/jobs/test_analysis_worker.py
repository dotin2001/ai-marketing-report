from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.ai import context as context_module
from app.ai.context import PreparedContext, prepare_context
from app.ai.openai_adapter import OpenAIAnalysisAdapter
from app.ai.output import NarrativeItem, NumericAssertion, StructuredOutput
from app.ai.prompt import PROMPT_VERSION
from app.ai.wire import WireOutput
from app.api.analysis_job_schemas import RetryAnalysisJobRequest
from app.api.report_schemas import UpdateDraftRequest
from app.core.config import Settings
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
from app.domain.reports import ReportServices
from app.jobs.analysis_worker import (
    AnalysisExecutionFailure,
    RunnerOutput,
    analysis_task,
    execute_analysis,
    fail_stale_running,
)
from tests.integration.db.test_analysis_jobs import seed_analysis_job
from tests.unit.ai.test_openai_adapter import FakeClient, response, wire_payload

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


@pytest.mark.asyncio
async def test_openai_adapter_worker_persists_actual_provenance_once(
    concurrent_engine: AsyncEngine,
    settings: Settings,
) -> None:
    sessions, owner, report, job_id, _semantic, numeric = await seeded(
        concurrent_engine, "adapter-success"
    )

    class CheckingResponses:
        def __init__(self) -> None:
            self.calls = 0

        async def parse(self, **_kwargs: Any) -> Any:
            self.calls += 1
            async with sessions() as session:
                job = await session.get(AnalysisJob, job_id)
                assert job is not None and job.state == "running"
            return response(model="provider-actual-model", response_id="resp_worker")

    client = SimpleNamespace(responses=CheckingResponses())
    runner = OpenAIAnalysisAdapter(settings, client)
    assert await execute_analysis(sessions, owner, report, job_id, 1, runner)
    assert not await execute_analysis(sessions, owner, report, job_id, 1, runner)
    assert client.responses.calls == 1
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.state == "succeeded"
        result = await session.scalar(select(AnalysisResult).where(AnalysisResult.job_id == job_id))
        assert result is not None and result.id == job.current_result_id
        assert result.model_identifier == "provider-actual-model"
        assert result.prompt_version == PROMPT_VERSION
        assert "resp_worker" in result.request_provenance
        assert result.numeric_source_identity == numeric
        assert (
            await session.scalars(
                select(AnalysisResult).where(
                    AnalysisResult.job_id == job_id,
                )
            )
        ).all() == [result]
    public = await AnalysisJobServices(sessions, "s" * 32).detail(owner, report, job_id)
    assert public.result is not None
    assert public.result.summary[0].content == "Performance was stable."
    assert public.result.model_identifier == "provider-actual-model"


@pytest.mark.asyncio
async def test_late_openai_response_cannot_attach_to_changed_draft(
    concurrent_engine: AsyncEngine,
    settings: Settings,
) -> None:
    sessions, owner, report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "adapter-late"
    )

    class ChangingResponses:
        async def parse(self, **_kwargs: Any) -> Any:
            async with sessions.begin() as session:
                job = await session.get(AnalysisJob, job_id)
                assert job is not None and job.state == "running"
                draft = await session.get(ReportDraft, job.draft_id)
                assert draft is not None
                draft.revision += 1
            return response()

    assert await execute_analysis(
        sessions,
        owner,
        report,
        job_id,
        1,
        OpenAIAnalysisAdapter(settings, SimpleNamespace(responses=ChangingResponses())),
    )
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.failure_code == "stale_result"
        assert job.current_result_id is None
        draft = await session.get(ReportDraft, job.draft_id)
        assert draft is not None and draft.revision == 2
        assert (
            await session.scalars(
                select(AnalysisResult).where(
                    AnalysisResult.job_id == job_id,
                )
            )
        ).all() == []


@pytest.mark.asyncio
async def test_saved_presentation_edit_survives_late_analysis(
    concurrent_engine: AsyncEngine, settings: Settings
) -> None:
    sessions, owner, report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "presentation-edit-during-analysis"
    )
    reports = ReportServices(sessions, "s" * 32)

    class EditingResponses:
        async def parse(self, **_kwargs: Any) -> Any:
            saved = await reports.update_draft(
                owner,
                report,
                UpdateDraftRequest.model_validate(
                    {
                        "expected_revision": 1,
                        "narrative": [
                            {
                                "section": "summary",
                                "content": "Owner's edit",
                                "classification": "user_claim",
                            }
                        ],
                        "limitations": [{"content": "Owner's limitation"}],
                        "claims": [{"content": "Owner's claim"}],
                    }
                ),
            )
            assert saved.revision == 2
            return response()

    assert await execute_analysis(
        sessions,
        owner,
        report,
        job_id,
        1,
        OpenAIAnalysisAdapter(settings, SimpleNamespace(responses=EditingResponses())),
    )
    detail = (await reports.detail(owner, report)).active_draft
    assert detail.revision == 2
    assert detail.narrative[0].content == "Owner's edit"
    assert detail.limitations[0].content == "Owner's limitation"
    assert detail.claims[0].content == "Owner's claim"
    assert detail.current_analysis_result_id is None
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.failure_code == "stale_result"
        assert (
            await session.scalar(select(AnalysisResult.id).where(AnalysisResult.job_id == job_id))
            is None
        )


@pytest.mark.asyncio
async def test_openai_failure_retry_and_old_delivery_use_one_result(
    concurrent_engine: AsyncEngine,
    settings: Settings,
) -> None:
    sessions, owner, report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "adapter-retry"
    )
    failed_client = FakeClient(TimeoutError("private source and prompt"))
    assert await execute_analysis(
        sessions, owner, report, job_id, 1, OpenAIAnalysisAdapter(settings, failed_client)
    )
    detail = await AnalysisJobServices(sessions, "s" * 32).detail(owner, report, job_id)
    assert detail.failure is not None and detail.failure.code == "provider_timeout"
    assert detail.failure.retryable is True
    assert "private source" not in str(detail)
    service = AnalysisJobServices(sessions, "s" * 32, publisher=lambda *_: None)
    retried, replayed = await service.retry(
        owner, report, job_id, RetryAnalysisJobRequest(expected_attempt_count=1), "retry-key"
    )
    assert retried.state == "queued" and retried.attempt_count == 2 and not replayed
    repeated, replayed = await service.retry(
        owner, report, job_id, RetryAnalysisJobRequest(expected_attempt_count=1), "retry-key"
    )
    assert repeated.id == retried.id and replayed
    good_client = FakeClient(response())
    runner = OpenAIAnalysisAdapter(settings, good_client)
    assert not await execute_analysis(sessions, owner, report, job_id, 1, runner)
    assert await execute_analysis(sessions, owner, report, job_id, 2, runner)
    assert not await execute_analysis(sessions, owner, report, job_id, 2, runner)
    assert len(good_client.responses.calls) == 1
    async with sessions() as session:
        results = (
            await session.scalars(
                select(AnalysisResult).where(
                    AnalysisResult.job_id == job_id,
                )
            )
        ).all()
        attempts = (
            await session.scalars(
                select(AnalysisJobAttempt)
                .where(
                    AnalysisJobAttempt.job_id == job_id,
                )
                .order_by(AnalysisJobAttempt.attempt_ordinal)
            )
        ).all()
        assert len(results) == 1
        assert [attempt.state for attempt in attempts] == ["failed", "succeeded"]


@pytest.mark.asyncio
async def test_provider_foreign_reference_fails_before_persistence(
    concurrent_engine: AsyncEngine,
    settings: Settings,
) -> None:
    sessions, owner, report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "adapter-foreign"
    )
    payload = wire_payload()
    payload["summary"][0]["metric_ids"] = [str(uuid4())]
    runner = OpenAIAnalysisAdapter(
        settings, FakeClient(response(parsed=WireOutput.model_validate(payload)))
    )
    assert await execute_analysis(sessions, owner, report, job_id, 1, runner)
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.failure_code == "invalid_structured_output"
        assert job.current_result_id is None
        assert (
            await session.scalars(
                select(AnalysisResult).where(
                    AnalysisResult.job_id == job_id,
                )
            )
        ).all() == []


@pytest.mark.asyncio
async def test_changed_dataset_blocks_provider_request(
    concurrent_engine: AsyncEngine,
    settings: Settings,
) -> None:
    sessions, owner, report_id, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "adapter-dataset-stale"
    )
    async with sessions.begin() as session:
        report = await session.get(Report, report_id)
        assert report is not None
        report.current_dataset_id = None
        report.current_metric_result_set_id = None
    client = FakeClient(response())
    assert await execute_analysis(
        sessions, owner, report_id, job_id, 1, OpenAIAnalysisAdapter(settings, client)
    )
    assert client.responses.calls == []
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.failure_code == "stale_result"
        assert job.current_result_id is None


@pytest.mark.asyncio
async def test_production_task_constructs_and_closes_openai_client(
    concurrent_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    valid_settings_data: dict[str, Any],
) -> None:
    sessions, owner, report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "production-task"
    )
    calls: list[dict[str, Any]] = []
    closed: list[bool] = []

    class FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)
            self.responses = FakeClient(response()).responses

        async def close(self) -> None:
            closed.append(True)

    for name, value in valid_settings_data.items():
        monkeypatch.setenv(name, str(value).lower() if isinstance(value, bool) else str(value))
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("AI_LOCAL_DISABLE_DOTENV", "1")
    monkeypatch.setattr("app.jobs.analysis_worker.AsyncOpenAI", FakeOpenAI)
    await asyncio.to_thread(analysis_task.run, str(owner), str(report), str(job_id), 1)
    assert len(calls) == 1 and calls[0]["max_retries"] == 0
    assert calls[0]["timeout"] == 60
    assert closed == [True]
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.state == "succeeded"


@pytest.mark.asyncio
async def test_production_configuration_failure_is_persisted_safely(
    concurrent_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    valid_settings_data: dict[str, Any],
) -> None:
    sessions, owner, report, job_id, _semantic, _numeric = await seeded(
        concurrent_engine, "production-config-failure"
    )
    for name, value in valid_settings_data.items():
        monkeypatch.setenv(name, str(value).lower() if isinstance(value, bool) else str(value))
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("AI_LOCAL_DISABLE_DOTENV", "1")
    monkeypatch.delenv("OPENAI_API_KEY")
    await asyncio.to_thread(analysis_task.run, str(owner), str(report), str(job_id), 1)
    async with sessions() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job is not None and job.state == "failed"
        assert job.failure_code == "provider_unavailable"
        assert job.failure_retryable is False
        assert job.failure_message == "Analysis could not be completed."
