from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.db import Base
from app.db.models import (
    AnalysisJob,
    AnalysisJobAttempt,
    AnalysisResult,
    AnalysisResultItem,
    CanonicalDataset,
    IdempotencyRecord,
    MetricResultSet,
    Report,
    ReportDraft,
)
from app.db.repositories import (
    ConcurrencyConflict,
    IdempotencyConflict,
    claim_analysis_job,
    create_analysis_job,
    fail_analysis_job,
    finish_analysis_job,
    resolve_idempotency,
    retry_analysis_job,
    save_draft_objectives,
)
from app.db.testing import validate_test_database
from tests.integration.db.conftest import seed_report
from tests.integration.db.test_datasets_and_metrics import seed_dataset_metric_aggregate

pytestmark = pytest.mark.postgres


@pytest.fixture
async def concurrent_engine() -> AsyncIterator[AsyncEngine]:
    target = validate_test_database(
        app_env=os.environ.get("APP_ENV"),
        test_database_url=os.environ.get("TEST_DATABASE_URL"),
        database_url=os.environ.get("DATABASE_URL"),
    )
    engine = create_async_engine(target.url, pool_pre_ping=False)
    table_names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))
        await engine.dispose()


async def seed_analysis_job(
    session: AsyncSession, *, subject: str, raw_key: str | None = None
) -> tuple[Report, CanonicalDataset, MetricResultSet, ReportDraft, AnalysisJob]:
    report, dataset, _row, metric_set, _metric = await seed_dataset_metric_aggregate(
        session, subject=subject
    )
    draft = await session.scalar(
        select(ReportDraft).where(
            ReportDraft.report_id == report.id,
            ReportDraft.is_active.is_(True),
        )
    )
    assert draft is not None
    identity = sha256(f"analysis-{subject}".encode()).digest()
    idempotency = None
    if raw_key is not None:
        idempotency = await resolve_idempotency(
            session,
            principal_id=report.owner_id,
            operation="create-analysis",
            scope_kind="report",
            scope_id=report.id,
            raw_key=raw_key,
            command_fingerprint=identity,
        )
    job = await create_analysis_job(
        session,
        owner_id=report.owner_id,
        report_id=report.id,
        semantic_input_identity=identity,
        dataset_id=dataset.id,
        metric_result_set_id=metric_set.id,
        draft_id=draft.id,
        draft_revision=draft.revision,
        objectives_revision=draft.revision,
        idempotency=idempotency,
    )
    return report, dataset, metric_set, draft, job


def analysis_result_for(
    report: Report, metric_set: MetricResultSet, job: AnalysisJob
) -> AnalysisResult:
    return AnalysisResult(
        owner_id=report.owner_id,
        report_id=report.id,
        job_id=job.id,
        semantic_input_identity=job.semantic_input_identity,
        model_identifier="test-model",
        prompt_version="analysis-v1",
        request_provenance="bounded-computed-metrics",
        numeric_source_identity=metric_set.identity,
    )


def analysis_item_for(report: Report) -> AnalysisResultItem:
    return AnalysisResultItem(
        owner_id=report.owner_id,
        report_id=report.id,
        result_id=uuid4(),
        section="summary",
        ordinal=1,
        classification="observation",
        content="CTR was unchanged.",
    )


@pytest.mark.asyncio
async def test_idempotency_equivalent_replay_returns_one_record(
    db_session: AsyncSession,
) -> None:
    owner, report, _ = await seed_report(db_session, subject="idem-owner")
    fingerprint = sha256(b"canonical-command").digest()
    first = await resolve_idempotency(
        db_session,
        principal_id=owner.id,
        operation="create-analysis",
        scope_kind="report",
        scope_id=report.id,
        raw_key="client-key",
        command_fingerprint=fingerprint,
    )
    replay = await resolve_idempotency(
        db_session,
        principal_id=owner.id,
        operation="create-analysis",
        scope_kind="report",
        scope_id=report.id,
        raw_key="client-key",
        command_fingerprint=fingerprint,
    )
    assert replay.id == first.id
    assert first.key_digest != b"client-key"


@pytest.mark.asyncio
async def test_idempotency_reuse_with_different_input_conflicts(
    db_session: AsyncSession,
) -> None:
    owner, report, _ = await seed_report(db_session, subject="idem-conflict")
    await resolve_idempotency(
        db_session,
        principal_id=owner.id,
        operation="create-analysis",
        scope_kind="report",
        scope_id=report.id,
        raw_key="same-key",
        command_fingerprint=sha256(b"one").digest(),
    )
    with pytest.raises(IdempotencyConflict):
        await resolve_idempotency(
            db_session,
            principal_id=owner.id,
            operation="create-analysis",
            scope_kind="report",
            scope_id=report.id,
            raw_key="same-key",
            command_fingerprint=sha256(b"two").digest(),
        )
    assert uuid4() != report.id


@pytest.mark.asyncio
async def test_analysis_job_claim_success_and_redelivery_are_atomic(
    db_session: AsyncSession,
) -> None:
    report, _dataset, metric_set, draft, job = await seed_analysis_job(
        db_session, subject="analysis-success"
    )
    assert await claim_analysis_job(
        db_session, owner_id=report.owner_id, report_id=report.id, job_id=job.id
    )
    assert not await claim_analysis_job(
        db_session, owner_id=report.owner_id, report_id=report.id, job_id=job.id
    )

    result = analysis_result_for(report, metric_set, job)
    attached = await finish_analysis_job(
        db_session,
        owner_id=report.owner_id,
        report_id=report.id,
        job_id=job.id,
        expected_attempt_count=1,
        result=result,
        items=[analysis_item_for(report)],
    )
    assert attached is True
    await db_session.refresh(job)
    await db_session.refresh(report)
    await db_session.refresh(draft)
    assert job.state == "succeeded" and job.current_result_id == result.id
    assert report.current_analysis_result_id == result.id
    assert draft.current_analysis_result_id == result.id
    attempts = (
        await db_session.scalars(
            select(AnalysisJobAttempt).where(AnalysisJobAttempt.job_id == job.id)
        )
    ).all()
    assert [(attempt.attempt_ordinal, attempt.state) for attempt in attempts] == [(1, "succeeded")]

    with pytest.raises(ConcurrencyConflict, match="completion state is stale"):
        await finish_analysis_job(
            db_session,
            owner_id=report.owner_id,
            report_id=report.id,
            job_id=job.id,
            expected_attempt_count=1,
            result=analysis_result_for(report, metric_set, job),
            items=[analysis_item_for(report)],
        )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(AnalysisResult).where(AnalysisResult.job_id == job.id)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_analysis_job_rejects_illegal_skip_without_partial_result(
    db_session: AsyncSession,
) -> None:
    report, _dataset, metric_set, _draft, job = await seed_analysis_job(
        db_session, subject="analysis-illegal-skip"
    )
    with pytest.raises(ConcurrencyConflict, match="completion state is stale"):
        await finish_analysis_job(
            db_session,
            owner_id=report.owner_id,
            report_id=report.id,
            job_id=job.id,
            expected_attempt_count=1,
            result=analysis_result_for(report, metric_set, job),
            items=[analysis_item_for(report)],
        )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(AnalysisResult).where(AnalysisResult.job_id == job.id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_analysis_failure_retries_once_only_for_unchanged_inputs(
    db_session: AsyncSession,
) -> None:
    report, _dataset, _metric_set, _draft, job = await seed_analysis_job(
        db_session, subject="analysis-retry"
    )
    assert await claim_analysis_job(
        db_session, owner_id=report.owner_id, report_id=report.id, job_id=job.id
    )
    await fail_analysis_job(
        db_session,
        owner_id=report.owner_id,
        report_id=report.id,
        job_id=job.id,
        expected_attempt_count=1,
        failure_code="provider_timeout",
        failure_message="Temporary provider timeout",
        retryable=True,
    )
    assert (
        await retry_analysis_job(
            db_session,
            owner_id=report.owner_id,
            report_id=report.id,
            job_id=job.id,
            expected_attempt_count=1,
        )
        == 2
    )
    with pytest.raises(ConcurrencyConflict, match="retry state or input is stale"):
        await retry_analysis_job(
            db_session,
            owner_id=report.owner_id,
            report_id=report.id,
            job_id=job.id,
            expected_attempt_count=1,
        )
    attempts = (
        await db_session.scalars(
            select(AnalysisJobAttempt)
            .where(AnalysisJobAttempt.job_id == job.id)
            .order_by(AnalysisJobAttempt.attempt_ordinal)
        )
    ).all()
    assert [(attempt.attempt_ordinal, attempt.state) for attempt in attempts] == [
        (1, "failed"),
        (2, "queued"),
    ]


@pytest.mark.asyncio
async def test_late_analysis_result_is_retained_but_not_attached(
    db_session: AsyncSession,
) -> None:
    report, _dataset, metric_set, draft, job = await seed_analysis_job(
        db_session, subject="analysis-stale-result"
    )
    assert await claim_analysis_job(
        db_session, owner_id=report.owner_id, report_id=report.id, job_id=job.id
    )
    assert (
        await save_draft_objectives(
            db_session,
            owner_id=report.owner_id,
            report_id=report.id,
            draft_id=draft.id,
            expected_revision=1,
            objectives=["Use the updated objective"],
        )
        == 2
    )
    result = analysis_result_for(report, metric_set, job)
    assert not await finish_analysis_job(
        db_session,
        owner_id=report.owner_id,
        report_id=report.id,
        job_id=job.id,
        expected_attempt_count=1,
        result=result,
        items=[analysis_item_for(report)],
    )
    await db_session.refresh(report)
    await db_session.refresh(draft)
    await db_session.refresh(job)
    assert job.state == "succeeded" and job.current_result_id == result.id
    assert report.current_analysis_result_id is None
    assert draft.current_analysis_result_id is None


@pytest.mark.asyncio
async def test_idempotent_analysis_replay_returns_original_job_and_attempt(
    db_session: AsyncSession,
) -> None:
    report, dataset, metric_set, draft, first = await seed_analysis_job(
        db_session, subject="analysis-idempotent-replay", raw_key="stable-client-key"
    )
    fingerprint = first.semantic_input_identity
    replay_record = await resolve_idempotency(
        db_session,
        principal_id=report.owner_id,
        operation="create-analysis",
        scope_kind="report",
        scope_id=report.id,
        raw_key="stable-client-key",
        command_fingerprint=fingerprint,
    )
    replay = await create_analysis_job(
        db_session,
        owner_id=report.owner_id,
        report_id=report.id,
        semantic_input_identity=fingerprint,
        dataset_id=dataset.id,
        metric_result_set_id=metric_set.id,
        draft_id=draft.id,
        draft_revision=draft.revision,
        objectives_revision=draft.revision,
        idempotency=replay_record,
    )
    assert replay.id == first.id
    assert replay_record.result_type == "analysis_job"
    assert replay_record.result_id == first.id
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AnalysisJobAttempt)
            .where(AnalysisJobAttempt.job_id == first.id)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_protected_mutation_rollback_removes_job_and_idempotency(
    db_session: AsyncSession,
) -> None:
    report, dataset, _row, metric_set, _metric = await seed_dataset_metric_aggregate(
        db_session, subject="analysis-rollback"
    )
    draft = await db_session.scalar(
        select(ReportDraft).where(
            ReportDraft.report_id == report.id,
            ReportDraft.is_active.is_(True),
        )
    )
    assert draft is not None
    identity = sha256(b"analysis-rollback").digest()
    with pytest.raises(RuntimeError, match="force rollback"):
        async with db_session.begin_nested():
            record = await resolve_idempotency(
                db_session,
                principal_id=report.owner_id,
                operation="create-analysis-rollback",
                scope_kind="report",
                scope_id=report.id,
                raw_key="rollback-key",
                command_fingerprint=identity,
            )
            await create_analysis_job(
                db_session,
                owner_id=report.owner_id,
                report_id=report.id,
                semantic_input_identity=identity,
                dataset_id=dataset.id,
                metric_result_set_id=metric_set.id,
                draft_id=draft.id,
                draft_revision=draft.revision,
                objectives_revision=draft.revision,
                idempotency=record,
            )
            raise RuntimeError("force rollback")
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(IdempotencyRecord)
            .where(IdempotencyRecord.operation == "create-analysis-rollback")
        )
        == 0
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AnalysisJob)
            .where(AnalysisJob.semantic_input_identity == identity)
        )
        == 0
    )


def test_idempotency_schema_excludes_raw_keys_and_request_bodies() -> None:
    assert "raw_key" not in IdempotencyRecord.__table__.c
    assert "request_body" not in IdempotencyRecord.__table__.c
    assert "key_digest" in IdempotencyRecord.__table__.c


@pytest.mark.asyncio
async def test_concurrent_duplicate_creation_and_idempotency_resolve_once(
    concurrent_engine: AsyncEngine,
) -> None:
    async with AsyncSession(concurrent_engine, expire_on_commit=False) as seed_session:
        async with seed_session.begin():
            report, dataset, _row, metric_set, _metric = await seed_dataset_metric_aggregate(
                seed_session, subject="analysis-concurrent-create"
            )
            draft = await seed_session.scalar(
                select(ReportDraft).where(
                    ReportDraft.report_id == report.id,
                    ReportDraft.is_active.is_(True),
                )
            )
            assert draft is not None
    identity = sha256(b"analysis-concurrent-create").digest()

    async def create_once() -> object:
        async with AsyncSession(concurrent_engine, expire_on_commit=False) as session:
            async with session.begin():
                job = await create_analysis_job(
                    session,
                    owner_id=report.owner_id,
                    report_id=report.id,
                    semantic_input_identity=identity,
                    dataset_id=dataset.id,
                    metric_result_set_id=metric_set.id,
                    draft_id=draft.id,
                    draft_revision=draft.revision,
                    objectives_revision=draft.revision,
                )
                return job.id

    job_ids = await asyncio.gather(create_once(), create_once())
    assert job_ids[0] == job_ids[1]

    async def resolve_once() -> object:
        async with AsyncSession(concurrent_engine, expire_on_commit=False) as session:
            async with session.begin():
                record = await resolve_idempotency(
                    session,
                    principal_id=report.owner_id,
                    operation="concurrent-analysis",
                    scope_kind="report",
                    scope_id=report.id,
                    raw_key="one-concurrent-key",
                    command_fingerprint=identity,
                )
                return (
                    await create_analysis_job(
                        session,
                        owner_id=report.owner_id,
                        report_id=report.id,
                        semantic_input_identity=identity,
                        dataset_id=dataset.id,
                        metric_result_set_id=metric_set.id,
                        draft_id=draft.id,
                        draft_revision=draft.revision,
                        objectives_revision=draft.revision,
                        idempotency=record,
                    )
                ).id

    replay_ids = await asyncio.gather(resolve_once(), resolve_once())
    assert replay_ids == job_ids
    async with AsyncSession(concurrent_engine) as verify:
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(AnalysisJob)
                .where(AnalysisJob.report_id == report.id)
            )
            == 1
        )
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(AnalysisJobAttempt)
                .where(AnalysisJobAttempt.job_id == job_ids[0])
            )
            == 1
        )
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.operation == "concurrent-analysis")
            )
            == 1
        )


@pytest.mark.asyncio
async def test_concurrent_cas_allocates_one_retry_and_one_result(
    concurrent_engine: AsyncEngine,
) -> None:
    async with AsyncSession(concurrent_engine, expire_on_commit=False) as seed_session:
        async with seed_session.begin():
            report, _dataset, metric_set, _draft, job = await seed_analysis_job(
                seed_session, subject="analysis-concurrent-cas"
            )

    async def claim_once() -> bool:
        async with AsyncSession(concurrent_engine) as session:
            async with session.begin():
                return await claim_analysis_job(
                    session,
                    owner_id=report.owner_id,
                    report_id=report.id,
                    job_id=job.id,
                )

    assert sorted(await asyncio.gather(claim_once(), claim_once())) == [False, True]
    async with AsyncSession(concurrent_engine) as session:
        async with session.begin():
            await fail_analysis_job(
                session,
                owner_id=report.owner_id,
                report_id=report.id,
                job_id=job.id,
                expected_attempt_count=1,
                failure_code="provider_timeout",
                failure_message="Temporary provider timeout",
                retryable=True,
            )

    async def retry_once() -> int | Exception:
        try:
            async with AsyncSession(concurrent_engine) as session:
                async with session.begin():
                    return await retry_analysis_job(
                        session,
                        owner_id=report.owner_id,
                        report_id=report.id,
                        job_id=job.id,
                        expected_attempt_count=1,
                    )
        except ConcurrencyConflict as error:
            return error

    retries = await asyncio.gather(retry_once(), retry_once())
    assert sum(value == 2 for value in retries if isinstance(value, int)) == 1
    assert sum(isinstance(value, ConcurrencyConflict) for value in retries) == 1
    async with AsyncSession(concurrent_engine) as session:
        async with session.begin():
            assert await claim_analysis_job(
                session,
                owner_id=report.owner_id,
                report_id=report.id,
                job_id=job.id,
            )

    async def finish_once() -> bool | Exception:
        try:
            async with AsyncSession(concurrent_engine) as session:
                async with session.begin():
                    return await finish_analysis_job(
                        session,
                        owner_id=report.owner_id,
                        report_id=report.id,
                        job_id=job.id,
                        expected_attempt_count=2,
                        result=analysis_result_for(report, metric_set, job),
                        items=[analysis_item_for(report)],
                    )
        except ConcurrencyConflict as error:
            return error

    completions = await asyncio.gather(finish_once(), finish_once())
    assert sum(value is True for value in completions) == 1
    assert sum(isinstance(value, ConcurrencyConflict) for value in completions) == 1
    async with AsyncSession(concurrent_engine) as verify:
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(AnalysisJobAttempt)
                .where(AnalysisJobAttempt.job_id == job.id)
            )
            == 2
        )
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(AnalysisResult)
                .where(AnalysisResult.job_id == job.id)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_analysis_result_pointer_cannot_cross_logical_jobs(
    db_session: AsyncSession,
) -> None:
    report, dataset, _row, metric_set, _metric = await seed_dataset_metric_aggregate(
        db_session, subject="analysis-pointer"
    )
    draft = await db_session.scalar(
        select(ReportDraft).where(
            ReportDraft.report_id == report.id,
            ReportDraft.is_active.is_(True),
        )
    )
    assert draft is not None
    jobs: list[AnalysisJob] = []
    for ordinal in (1, 2):
        job = AnalysisJob(
            owner_id=report.owner_id,
            report_id=report.id,
            semantic_input_identity=sha256(f"analysis-{ordinal}".encode()).digest(),
            dataset_id=dataset.id,
            metric_result_set_id=metric_set.id,
            draft_id=draft.id,
            draft_revision=draft.revision,
            objectives_revision=draft.revision,
            state="queued",
            attempt_count=1,
        )
        db_session.add(job)
        await db_session.flush()
        db_session.add(
            AnalysisJobAttempt(
                owner_id=report.owner_id,
                report_id=report.id,
                job_id=job.id,
                attempt_ordinal=1,
                state="queued",
                queued_at=datetime.now(UTC),
            )
        )
        jobs.append(job)
    await db_session.flush()
    result = AnalysisResult(
        owner_id=report.owner_id,
        report_id=report.id,
        job_id=jobs[1].id,
        semantic_input_identity=jobs[1].semantic_input_identity,
        model_identifier="test-model",
        prompt_version="analysis-v1",
        request_provenance="bounded-test-input",
        numeric_source_identity=metric_set.identity,
    )
    db_session.add(result)
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            jobs[0].current_result_id = result.id
            await db_session.flush()
            await db_session.execute(
                text("SET CONSTRAINTS fk_analysis_jobs_current_result IMMEDIATE")
            )


@pytest.mark.asyncio
async def test_analysis_attempt_rejects_nonpositive_ordinal(db_session: AsyncSession) -> None:
    report, dataset, _row, metric_set, _metric = await seed_dataset_metric_aggregate(
        db_session, subject="analysis-attempt-ordinal"
    )
    draft = await db_session.scalar(
        select(ReportDraft).where(
            ReportDraft.report_id == report.id,
            ReportDraft.is_active.is_(True),
        )
    )
    assert draft is not None
    job = AnalysisJob(
        owner_id=report.owner_id,
        report_id=report.id,
        semantic_input_identity=sha256(b"invalid-attempt").digest(),
        dataset_id=dataset.id,
        metric_result_set_id=metric_set.id,
        draft_id=draft.id,
        draft_revision=draft.revision,
        objectives_revision=draft.revision,
        state="queued",
        attempt_count=1,
    )
    db_session.add(job)
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                AnalysisJobAttempt(
                    owner_id=report.owner_id,
                    report_id=report.id,
                    job_id=job.id,
                    attempt_ordinal=0,
                    state="queued",
                    queued_at=datetime.now(UTC),
                )
            )
            await db_session.flush()
