from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.api.analysis_job_schemas import CreateAnalysisJobRequest, RetryAnalysisJobRequest
from app.db.models import AnalysisJob, AnalysisJobAttempt, ReportDraft
from app.db.repositories import (
    ConcurrencyConflict,
    IdempotencyConflict,
    claim_analysis_job,
    fail_analysis_job,
)
from app.domain.analysis_jobs import AnalysisJobServices
from app.domain.assets import ResourceNotFound
from tests.integration.db.test_datasets_and_metrics import seed_dataset_metric_aggregate

pytestmark = pytest.mark.postgres
pytest_plugins = ("tests.integration.db.test_analysis_jobs",)


@pytest.mark.asyncio
async def test_service_creation_recovery_retry_and_owner_scope(
    concurrent_engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sessions = async_sessionmaker(concurrent_engine, expire_on_commit=False)
    async with sessions() as session:
        report, dataset, _row, metrics, _metric = await seed_dataset_metric_aggregate(
            session, subject="service-create"
        )
        draft = await session.scalar(
            select(ReportDraft).where(
                ReportDraft.report_id == report.id, ReportDraft.is_active.is_(True)
            )
        )
        assert draft is not None
        await session.commit()
    delivered: list[tuple[object, object, object, int]] = []

    def publisher(owner: object, report_id: object, job_id: object, ordinal: int) -> None:
        delivered.append((owner, report_id, job_id, ordinal))
        raise RuntimeError("secret-broker-payload")

    service = AnalysisJobServices(sessions, "s" * 32, publisher=publisher)
    command = CreateAnalysisJobRequest(
        expected_revision=draft.revision,
        dataset_id=dataset.id,
        metric_result_set_id=metrics.id,
    )
    detail, replayed = await service.create(report.owner_id, report.id, command, "create-one")
    assert not replayed and detail.state == "queued" and len(detail.attempts) == 1
    assert delivered == [(report.owner_id, report.id, detail.id, 1)]
    replay, replayed = await service.create(report.owner_id, report.id, command, "create-one")
    assert replayed and replay.id == detail.id
    assert await service.reconcile() == 1
    assert delivered[-1] == (report.owner_id, report.id, detail.id, 1)
    assert "secret-broker-payload" not in caplog.text
    with pytest.raises(IdempotencyConflict):
        await service.create(
            report.owner_id,
            report.id,
            CreateAnalysisJobRequest(
                expected_revision=draft.revision,
                dataset_id=uuid4(),
            ),
            "create-one",
        )
    with pytest.raises(ConcurrencyConflict):
        await service.create(
            report.owner_id,
            report.id,
            CreateAnalysisJobRequest(
                expected_revision=draft.revision + 1,
            ),
            "create-stale",
        )
    with pytest.raises(ResourceNotFound):
        await service.detail(uuid4(), report.id, detail.id)
    listed, page = await service.list(report.owner_id, report.id, 1, None)
    assert len(listed) == 1 and not page.has_more
    async with sessions() as session:
        assert await claim_analysis_job(
            session,
            owner_id=report.owner_id,
            report_id=report.id,
            job_id=detail.id,
            expected_attempt_count=1,
        )
        await fail_analysis_job(
            session,
            owner_id=report.owner_id,
            report_id=report.id,
            job_id=detail.id,
            expected_attempt_count=1,
            failure_code="provider_unavailable",
            failure_message="Unavailable.",
            retryable=True,
        )
        await session.commit()
    retried, replayed = await service.retry(
        report.owner_id,
        report.id,
        detail.id,
        RetryAnalysisJobRequest(expected_attempt_count=1),
        "retry-one",
    )
    assert not replayed and retried.state == "queued" and retried.attempt_count == 2
    retried_again, replayed = await service.retry(
        report.owner_id,
        report.id,
        detail.id,
        RetryAnalysisJobRequest(expected_attempt_count=1),
        "retry-one",
    )
    assert replayed and retried_again.attempt_count == 2
    with pytest.raises(ConcurrencyConflict):
        await service.retry(
            report.owner_id,
            report.id,
            detail.id,
            RetryAnalysisJobRequest(expected_attempt_count=1),
            "retry-two",
        )
    async with sessions() as session:
        assert (
            len(
                (
                    await session.scalars(
                        select(AnalysisJobAttempt).where(AnalysisJobAttempt.job_id == detail.id)
                    )
                ).all()
            )
            == 2
        )
        assert (await session.get(AnalysisJob, detail.id)).state == "queued"
