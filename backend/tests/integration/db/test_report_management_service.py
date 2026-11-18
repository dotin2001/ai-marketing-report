from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.report_schemas import CreateReportRequest, MetadataPatchRequest, ObjectivesPatchRequest
from app.db.models import (
    CanonicalDataset,
    DraftNarrativeItem,
    DraftObjective,
    IdempotencyRecord,
    Principal,
    Report,
    ReportDraft,
    ReportSource,
    ReportVersion,
)
from app.db.repositories import (
    ConcurrencyConflict,
    IdempotencyConflict,
    attach_source,
    confirm_source_review,
    create_analysis_job,
)
from app.db.testing import validate_test_database
from app.domain.reports import InvalidCursor, ReportNotFound, ReportServices
from app.domain.versions import save_current_report_version
from tests.integration.db.test_datasets_and_metrics import seed_dataset_metric_aggregate

pytestmark = pytest.mark.postgres


def request(name: str = "Report") -> CreateReportRequest:
    return CreateReportRequest.model_validate(
        {
            "name": name,
            "period": {"start_date": "2026-01-01", "end_date": "2026-01-31"},
            "objectives": ["Explain performance"],
        }
    )


@pytest.mark.asyncio
async def test_period_change_clears_current_derived_references_but_retains_history(
    db_session: AsyncSession,
) -> None:
    report, dataset, _row, metric_set, _metric = await seed_dataset_metric_aggregate(
        db_session, subject=str(uuid4())
    )
    await db_session.flush()
    assert db_session.bind is not None
    service = ReportServices(
        async_sessionmaker(
            db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ),
        "x" * 32,
    )
    before = await service.detail(report.owner_id, report.id)
    assert before.stage == "analysis_ready"
    assert before.current_dataset_id == dataset.id
    draft = await db_session.scalar(select(ReportDraft).where(ReportDraft.report_id == report.id))
    assert draft is not None
    await create_analysis_job(
        db_session,
        owner_id=report.owner_id,
        report_id=report.id,
        semantic_input_identity=sha256(b"stage-test").digest(),
        dataset_id=dataset.id,
        metric_result_set_id=metric_set.id,
        draft_id=draft.id,
        draft_revision=1,
        objectives_revision=1,
    )
    assert (await service.detail(report.owner_id, report.id)).stage == "analysis_pending"
    renamed = await service.update_metadata(
        report.owner_id, report.id, MetadataPatchRequest(expected_revision=1, name="Renamed")
    )
    assert renamed.stage == "analysis_pending"
    assert renamed.current_dataset_id == dataset.id
    assert renamed.current_metric_result_set_id == metric_set.id
    edited = await service.update_objectives(
        report.owner_id,
        report.id,
        ObjectivesPatchRequest(expected_revision=2, objectives=["Changed objective"]),
    )
    assert edited.revision == 3
    assert (await service.detail(report.owner_id, report.id)).stage == "analysis_ready"
    await db_session.refresh(draft)
    await db_session.refresh(report)
    version = await save_current_report_version(
        db_session,
        owner_id=report.owner_id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=3,
        template_version="report-v1",
        idempotency_key="version-stage",
    )
    await db_session.flush()
    assert (await service.detail(report.owner_id, report.id)).stage == "versioned"
    after = await service.update_metadata(
        report.owner_id,
        report.id,
        MetadataPatchRequest.model_validate(
            {
                "expected_revision": 3,
                "period": {"start_date": "2026-02-01", "end_date": "2026-02-28"},
            }
        ),
    )
    assert after.stage == "source_review"
    assert after.current_source_id == before.current_source_id
    assert after.current_dataset_id is None
    assert after.current_metric_result_set_id is None
    assert after.current_analysis_result_id is None
    assert (
        await db_session.scalar(select(ReportVersion.id).where(ReportVersion.id == version.id))
        == version.id
    )
    assert (
        await db_session.scalar(
            select(CanonicalDataset.id).where(CanonicalDataset.id == dataset.id)
        )
        == dataset.id
    )


@pytest.mark.asyncio
async def test_report_service_create_replay_updates_and_pages(db_session: AsyncSession) -> None:
    owner = Principal(identity_namespace="test", subject=str(uuid4()))
    other = Principal(identity_namespace="test", subject=str(uuid4()))
    db_session.add_all([owner, other])
    await db_session.flush()
    assert db_session.bind is not None
    service = ReportServices(
        async_sessionmaker(
            db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ),
        "x" * 32,
    )

    first, replayed = await service.create(owner.id, request("  First  "), "key-1")
    assert not replayed and first.name == "First"
    assert first.active_draft.revision == 1 and first.stage == "created"
    assert first.current_source_id is None and first.latest_version is None
    again, replayed = await service.create(owner.id, request("First"), "key-1")
    assert replayed and again.id == first.id
    with pytest.raises(IdempotencyConflict):
        await service.create(owner.id, request("Different"), "key-1")
    assert (
        await db_session.scalar(
            select(func.count()).select_from(Report).where(Report.owner_id == owner.id)
        )
        == 1
    )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(ReportDraft).where(ReportDraft.report_id == first.id)
        )
        == 1
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(IdempotencyRecord)
            .where(IdempotencyRecord.principal_id == owner.id)
        )
        == 1
    )
    for model in (ReportSource, ReportVersion):
        assert (
            await db_session.scalar(
                select(func.count()).select_from(model).where(model.report_id == first.id)
            )
            == 0
        )

    source = ReportSource(
        owner_id=owner.id,
        report_id=first.id,
        source_type="text",
        checksum_sha256=b"s" * 32,
        byte_size=4,
        media_type="text/plain",
        encoding="utf-8",
        inline_text="safe",
    )
    await attach_source(db_session, owner_id=owner.id, report_id=first.id, source=source)
    confirmed = await confirm_source_review(
        db_session,
        owner_id=owner.id,
        report_id=first.id,
        source_id=source.id,
        source_checksum=b"s" * 32,
        confirmed_by=owner.id,
    )
    assert (await service.detail(owner.id, first.id)).stage == "analysis_ready"
    db_session.add(
        DraftNarrativeItem(
            owner_id=owner.id,
            report_id=first.id,
            draft_id=first.active_draft.id,
            section="summary",
            ordinal=1,
            content="Original narrative",
            classification="observation",
        )
    )
    await db_session.flush()

    with pytest.raises(ReportNotFound):
        await service.detail(other.id, first.id)
    with pytest.raises(ReportNotFound):
        await service.update_metadata(
            other.id, first.id, MetadataPatchRequest(expected_revision=999, name="Foreign")
        )
    with pytest.raises(ReportNotFound):
        await service.update_objectives(
            other.id,
            first.id,
            ObjectivesPatchRequest(expected_revision=999, objectives=["Foreign"]),
        )
    with pytest.raises(ReportNotFound):
        await service.detail(owner.id, uuid4())
    renamed = await service.update_metadata(
        owner.id, first.id, MetadataPatchRequest(expected_revision=1, name=" New name ")
    )
    assert renamed.name == "New name" and renamed.active_draft.revision == 2
    assert renamed.stage == "analysis_ready" and renamed.current_source_id == source.id
    original_replay, replayed = await service.create(owner.id, request("First"), "key-1")
    assert replayed and original_replay.model_dump(mode="json") == first.model_dump(mode="json")
    same = await service.update_metadata(
        owner.id, first.id, MetadataPatchRequest(expected_revision=2, name="New name")
    )
    assert same.active_draft.revision == 2
    with pytest.raises(ConcurrencyConflict):
        await service.update_metadata(
            owner.id, first.id, MetadataPatchRequest(expected_revision=1, name="Stale")
        )
    edited = await service.update_objectives(
        owner.id, first.id, ObjectivesPatchRequest(expected_revision=2, objectives=[" New goal "])
    )
    assert edited.revision == 3 and edited.objectives == ["New goal"]
    assert edited.narrative[0].content == "Original narrative"
    with pytest.raises(ConcurrencyConflict):
        await service.update_objectives(
            owner.id,
            first.id,
            ObjectivesPatchRequest(expected_revision=2, objectives=["Stale goal"]),
        )
    draft = await db_session.scalar(select(ReportDraft).where(ReportDraft.id == edited.id))
    assert draft is not None and draft.objectives_revision == 3
    changed = await service.update_metadata(
        owner.id,
        first.id,
        MetadataPatchRequest.model_validate(
            {
                "expected_revision": 3,
                "period": {"start_date": "2026-02-01", "end_date": "2026-02-28"},
            }
        ),
    )
    assert changed.active_draft.revision == 4
    assert changed.period.start_date == date(2026, 2, 1)
    assert changed.stage == "source_review" and changed.current_source_id == source.id
    assert confirmed.period_start == date(2026, 1, 1)
    returned = await service.update_metadata(
        owner.id,
        first.id,
        MetadataPatchRequest.model_validate(
            {
                "expected_revision": 4,
                "period": {"start_date": "2026-01-01", "end_date": "2026-01-31"},
            }
        ),
    )
    assert returned.stage == "source_review"
    current_report = await db_session.scalar(select(Report).where(Report.id == first.id))
    assert current_report is not None
    await db_session.refresh(current_report)
    assert current_report.period_revision == 3
    renewed = await confirm_source_review(
        db_session,
        owner_id=owner.id,
        report_id=first.id,
        source_id=source.id,
        source_checksum=b"s" * 32,
        confirmed_by=owner.id,
    )
    assert renewed.period_revision == 3
    assert (await service.detail(owner.id, first.id)).stage == "analysis_ready"
    assert (await service.detail(owner.id, first.id)).objectives == ["New goal"]

    for ordinal in range(3):
        await service.create(owner.id, request(f"Next {ordinal}"), f"key-{ordinal + 2}")
    seen: list[UUID] = []
    cursor = None
    first_cursor: str | None = None
    while True:
        rows, page = await service.list(owner.id, 2, cursor)
        seen.extend(row.id for row in rows)
        if not page.has_more:
            assert page.next_cursor is None
            break
        assert page.next_cursor is not None
        cursor = page.next_cursor
        if first_cursor is None:
            first_cursor = cursor
    assert len(seen) == 4 and len(set(seen)) == 4
    assert (await service.list(other.id, 25, None))[0] == []
    assert first_cursor is not None
    inserted, _ = await service.create(owner.id, request("Inserted"), "inserted")
    await db_session.execute(
        update(Report)
        .where(Report.id == inserted.id)
        .values(created_at=datetime.now(UTC) + timedelta(days=1))
    )
    resumed, _page = await service.list(owner.id, 2, first_cursor)
    assert inserted.id not in {item.id for item in resumed}
    assert not {item.id for item in resumed} & set(seen[:2])
    with pytest.raises(InvalidCursor):
        await service.list(other.id, 2, first_cursor)
    with pytest.raises(InvalidCursor):
        await service.list(owner.id, 2, first_cursor + "x")


@pytest.mark.asyncio
async def test_concurrent_create_uses_one_idempotent_result() -> None:
    target = validate_test_database(
        app_env=os.environ.get("APP_ENV"),
        test_database_url=os.environ.get("TEST_DATABASE_URL"),
        database_url=os.environ.get("DATABASE_URL"),
    )
    engine = create_async_engine(target.url, pool_pre_ping=False)
    owner_id = uuid4()
    try:
        async with AsyncSession(engine) as setup, setup.begin():
            setup.add(Principal(id=owner_id, identity_namespace="test", subject=str(owner_id)))
        service = ReportServices(async_sessionmaker(engine, expire_on_commit=False), "x" * 32)
        first, second = await asyncio.gather(
            service.create(owner_id, request(), "concurrent-key"),
            service.create(owner_id, request(), "concurrent-key"),
        )
        assert first[0].id == second[0].id
        assert sorted([first[1], second[1]]) == [False, True]
        edits = await asyncio.gather(
            service.update_metadata(
                owner_id, first[0].id, MetadataPatchRequest(expected_revision=1, name="First edit")
            ),
            service.update_metadata(
                owner_id, first[0].id, MetadataPatchRequest(expected_revision=1, name="Second edit")
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, ConcurrencyConflict) for result in edits) == 1
        assert sum(not isinstance(result, BaseException) for result in edits) == 1
        async with AsyncSession(engine) as verify:
            assert (
                await verify.scalar(
                    select(func.count()).select_from(Report).where(Report.owner_id == owner_id)
                )
                == 1
            )
            assert (
                await verify.scalar(
                    select(func.count())
                    .select_from(ReportDraft)
                    .where(ReportDraft.owner_id == owner_id)
                )
                == 1
            )
            assert (
                await verify.scalar(
                    select(func.count())
                    .select_from(IdempotencyRecord)
                    .where(IdempotencyRecord.principal_id == owner_id)
                )
                == 1
            )
    finally:
        async with AsyncSession(engine) as cleanup, cleanup.begin():
            reports = list(
                await cleanup.scalars(select(Report.id).where(Report.owner_id == owner_id))
            )
            await cleanup.execute(delete(DraftObjective).where(DraftObjective.owner_id == owner_id))
            await cleanup.execute(delete(ReportDraft).where(ReportDraft.owner_id == owner_id))
            await cleanup.execute(
                delete(IdempotencyRecord).where(IdempotencyRecord.principal_id == owner_id)
            )
            await cleanup.execute(delete(Report).where(Report.id.in_(reports)))
            await cleanup.execute(delete(Principal).where(Principal.id == owner_id))
        await engine.dispose()
