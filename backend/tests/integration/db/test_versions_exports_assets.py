from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import date
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.db import Base
from app.db.models import (
    AnalysisResult,
    AnalysisResultItem,
    DraftClaim,
    DraftLimitation,
    DraftNarrativeItem,
    DraftObjective,
    FileAsset,
    PdfExportAttempt,
    ReportDraft,
    ReportVersion,
)
from app.db.repositories import (
    ConcurrencyConflict,
    claim_analysis_job,
    claim_pdf_export,
    create_analysis_job,
    create_pdf_export,
    create_report_version,
    fail_pdf_export,
    finish_analysis_job,
    finish_pdf_export,
    get_pdf_export,
    get_version,
    list_pdf_exports,
    list_versions,
    report_snapshot_identity,
    resolve_idempotency,
    restore_version_to_draft,
    retry_pdf_export,
    save_draft_objectives,
)
from app.db.snapshots import ReportVersionSnapshot
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


def snapshot(report_id: UUID, *, limitation: str | None = None) -> ReportVersionSnapshot:
    return ReportVersionSnapshot.model_validate(
        {
            "schema_version": 1,
            "report_id": report_id,
            "report_name": "Quarterly report",
            "period_start": date(2026, 1, 1),
            "period_end": date(2026, 3, 31),
            "objectives": ["Explain acquisition performance"],
            "source": {
                "source_id": report_id,
                "source_type": "text",
                "checksum_sha256": "a" * 64,
                "byte_size": 1,
                "media_type": "text/plain",
            },
            "metrics": [],
            "narrative": [],
            "limitations": [limitation] if limitation else [],
            "claims": [],
            "template_version": "report-v1",
        }
    )


@pytest.mark.asyncio
async def test_version_is_sequential_owner_scoped_and_database_immutable(
    db_session: AsyncSession,
) -> None:
    owner, report, draft = await seed_report(db_session, subject="version-owner")
    version_snapshot = snapshot(report.id)
    version = await create_report_version(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        snapshot=version_snapshot,
        snapshot_identity=report_snapshot_identity(version_snapshot),
        template_version="report-v1",
    )
    await db_session.flush()
    assert version.version_number == 1
    assert [
        item.id for item in await list_versions(db_session, owner_id=owner.id, report_id=report.id)
    ] == [version.id]
    with pytest.raises(DBAPIError, match="immutable table report_versions rejects UPDATE"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE report_versions SET template_version = 'changed' WHERE id = :id"),
                {"id": version.id},
            )


@pytest.mark.asyncio
async def test_version_idempotency_replays_and_stale_revision_is_rejected(
    db_session: AsyncSession,
) -> None:
    owner, report, draft = await seed_report(db_session, subject="version-idempotency")
    version_snapshot = snapshot(report.id)
    identity = report_snapshot_identity(version_snapshot)
    record = await resolve_idempotency(
        db_session,
        principal_id=owner.id,
        operation="create-version",
        scope_kind="report",
        scope_id=report.id,
        raw_key="save-version-once",
        command_fingerprint=identity,
    )
    first = await create_report_version(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        snapshot=version_snapshot,
        snapshot_identity=identity,
        template_version="report-v1",
        idempotency=record,
    )
    replay_record = await resolve_idempotency(
        db_session,
        principal_id=owner.id,
        operation="create-version",
        scope_kind="report",
        scope_id=report.id,
        raw_key="save-version-once",
        command_fingerprint=identity,
    )
    replay = await create_report_version(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        snapshot=version_snapshot,
        snapshot_identity=identity,
        template_version="report-v1",
        idempotency=replay_record,
    )
    assert replay.id == first.id and replay.version_number == 1
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ReportVersion)
            .where(ReportVersion.report_id == report.id)
        )
        == 1
    )

    await save_draft_objectives(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        objectives=["Changed objective"],
    )
    changed_snapshot = snapshot(report.id, limitation="Later snapshot")
    with pytest.raises(ConcurrencyConflict, match="active draft revision is stale"):
        await create_report_version(
            db_session,
            owner_id=owner.id,
            report_id=report.id,
            draft_id=draft.id,
            expected_revision=1,
            snapshot=changed_snapshot,
            snapshot_identity=report_snapshot_identity(changed_snapshot),
            template_version="report-v1",
        )


@pytest.mark.asyncio
async def test_rolled_back_version_does_not_consume_number(db_session: AsyncSession) -> None:
    owner, report, draft = await seed_report(db_session, subject="version-rollback-gap")
    rolled_back = snapshot(report.id, limitation="rolled back")
    with pytest.raises(RuntimeError, match="force rollback"):
        async with db_session.begin_nested():
            await create_report_version(
                db_session,
                owner_id=owner.id,
                report_id=report.id,
                draft_id=draft.id,
                expected_revision=1,
                snapshot=rolled_back,
                snapshot_identity=report_snapshot_identity(rolled_back),
                template_version="report-v1",
            )
            raise RuntimeError("force rollback")
    committed_snapshot = snapshot(report.id, limitation="committed")
    committed = await create_report_version(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        snapshot=committed_snapshot,
        snapshot_identity=report_snapshot_identity(committed_snapshot),
        template_version="report-v1",
    )
    assert committed.version_number == 1


@pytest.mark.asyncio
async def test_concurrent_versions_are_sequential_without_gaps(
    concurrent_engine: AsyncEngine,
) -> None:
    async with AsyncSession(concurrent_engine, expire_on_commit=False) as seed_session:
        async with seed_session.begin():
            owner, report, draft = await seed_report(
                seed_session, subject="version-concurrent-allocation"
            )

    async def create_once(label: str) -> tuple[int, UUID]:
        version_snapshot = snapshot(report.id, limitation=label)
        identity = report_snapshot_identity(version_snapshot)
        async with AsyncSession(concurrent_engine, expire_on_commit=False) as session:
            async with session.begin():
                record = await resolve_idempotency(
                    session,
                    principal_id=owner.id,
                    operation="create-version",
                    scope_kind="report",
                    scope_id=report.id,
                    raw_key=f"version-{label}",
                    command_fingerprint=identity,
                )
                version = await create_report_version(
                    session,
                    owner_id=owner.id,
                    report_id=report.id,
                    draft_id=draft.id,
                    expected_revision=1,
                    snapshot=version_snapshot,
                    snapshot_identity=identity,
                    template_version="report-v1",
                    idempotency=record,
                )
                return version.version_number, version.id

    created = await asyncio.gather(create_once("one"), create_once("two"))
    assert sorted(number for number, _ in created) == [1, 2]
    async with AsyncSession(concurrent_engine) as verify:
        numbers = (
            await verify.scalars(
                select(ReportVersion.version_number)
                .where(ReportVersion.report_id == report.id)
                .order_by(ReportVersion.version_number)
            )
        ).all()
        assert list(numbers) == [1, 2]


@pytest.mark.asyncio
async def test_pdf_retry_reuses_version_and_success_requires_bound_asset(
    db_session: AsyncSession,
) -> None:
    owner, report, draft = await seed_report(db_session, subject="pdf-export")
    version_snapshot = snapshot(report.id)
    version = await create_report_version(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        snapshot=version_snapshot,
        snapshot_identity=report_snapshot_identity(version_snapshot),
        template_version="report-v1",
    )
    input_identity = sha256(version.snapshot_identity + version.template_version.encode()).digest()
    export = await create_pdf_export(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        version_id=version.id,
        input_identity=input_identity,
    )
    replay = await create_pdf_export(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        version_id=version.id,
        input_identity=input_identity,
    )
    assert replay.id == export.id
    assert await claim_pdf_export(
        db_session, owner_id=owner.id, report_id=report.id, export_id=export.id
    )
    await fail_pdf_export(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        export_id=export.id,
        expected_attempt_count=1,
        failure_code="renderer_timeout",
        failure_message="Renderer timed out",
        retryable=True,
    )
    assert (
        await retry_pdf_export(
            db_session,
            owner_id=owner.id,
            report_id=report.id,
            export_id=export.id,
            expected_attempt_count=1,
        )
        == 2
    )
    assert await claim_pdf_export(
        db_session, owner_id=owner.id, report_id=report.id, export_id=export.id
    )
    pdf_bytes = b"%PDF-1.7\n% test"
    asset = FileAsset(
        owner_id=owner.id,
        report_id=report.id,
        purpose="generated_pdf",
        environment="test",
        bucket="private-test",
        object_key=f"pdf/{uuid4()}.pdf",
        safe_filename="report.pdf",
        content_type="application/pdf",
        byte_size=len(pdf_bytes),
        checksum_sha256=sha256(pdf_bytes).digest(),
    )
    await finish_pdf_export(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        export_id=export.id,
        expected_attempt_count=2,
        asset=asset,
    )
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await db_session.refresh(export)
    assert export.state == "succeeded" and export.generated_asset_id == asset.id
    assert asset.export_id == export.id and asset.version_id == version.id
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ReportVersion)
            .where(ReportVersion.report_id == report.id)
        )
        == 1
    )
    attempts = (
        await db_session.scalars(
            select(PdfExportAttempt)
            .where(PdfExportAttempt.export_id == export.id)
            .order_by(PdfExportAttempt.attempt_ordinal)
        )
    ).all()
    assert [(item.attempt_ordinal, item.state) for item in attempts] == [
        (1, "failed"),
        (2, "succeeded"),
    ]
    with pytest.raises(DBAPIError, match="immutable table file_assets rejects UPDATE"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE file_assets SET safe_filename = 'changed.pdf' WHERE id = :id"),
                {"id": asset.id},
            )
    with pytest.raises(DBAPIError, match="immutable table file_assets rejects DELETE"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM file_assets WHERE id = :id"), {"id": asset.id}
            )


@pytest.mark.asyncio
async def test_pdf_failure_has_no_asset_and_wrong_purpose_is_rejected(
    db_session: AsyncSession,
) -> None:
    owner, report, draft = await seed_report(db_session, subject="pdf-invalid-asset")
    version_snapshot = snapshot(report.id)
    version = await create_report_version(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        snapshot=version_snapshot,
        snapshot_identity=report_snapshot_identity(version_snapshot),
        template_version="report-v1",
    )
    export = await create_pdf_export(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        version_id=version.id,
        input_identity=sha256(
            version.snapshot_identity + version.template_version.encode()
        ).digest(),
    )
    assert await claim_pdf_export(
        db_session, owner_id=owner.id, report_id=report.id, export_id=export.id
    )
    wrong = FileAsset(
        owner_id=owner.id,
        report_id=report.id,
        purpose="source_csv",
        environment="test",
        bucket="private-test",
        object_key=f"source/{uuid4()}.csv",
        safe_filename="wrong.csv",
        content_type="text/csv",
        byte_size=3,
        checksum_sha256=sha256(b"csv").digest(),
    )
    with pytest.raises(ValueError, match="asset binding is invalid"):
        await finish_pdf_export(
            db_session,
            owner_id=owner.id,
            report_id=report.id,
            export_id=export.id,
            expected_attempt_count=1,
            asset=wrong,
        )
    await fail_pdf_export(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        export_id=export.id,
        expected_attempt_count=1,
        failure_code="invalid_render",
        failure_message="Rendered bytes were invalid",
        retryable=False,
    )
    await db_session.refresh(export)
    assert export.state == "failed"
    assert export.generated_asset_id is None and export.generated_asset_purpose is None
    assert (
        await db_session.scalar(
            select(func.count()).select_from(FileAsset).where(FileAsset.report_id == report.id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_version_export_queries_are_owner_scoped_and_restore_safe_snapshot(
    db_session: AsyncSession,
) -> None:
    owner, report, draft = await seed_report(db_session, subject="version-restore-owner")
    other, _other_report, _other_draft = await seed_report(
        db_session, subject="version-restore-other"
    )
    version_snapshot = ReportVersionSnapshot.model_validate(
        {
            **snapshot(report.id, limitation="Use directional interpretation only").model_dump(
                mode="json"
            ),
            "narrative": [
                {
                    "item_id": str(uuid4()),
                    "section": "summary",
                    "ordinal": 1,
                    "classification": "observation",
                    "content": "Performance was stable.",
                }
            ],
            "claims": [
                {
                    "claim_id": str(uuid4()),
                    "ordinal": 1,
                    "classification": "user_claim",
                    "content": "The campaign prioritized awareness.",
                }
            ],
        }
    )
    version = await create_report_version(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        snapshot=version_snapshot,
        snapshot_identity=report_snapshot_identity(version_snapshot),
        template_version="report-v1",
    )
    input_identity = sha256(version.snapshot_identity + version.template_version.encode()).digest()
    export = await create_pdf_export(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        version_id=version.id,
        input_identity=input_identity,
    )
    assert (
        await get_version(db_session, owner_id=other.id, report_id=report.id, version_id=version.id)
        is None
    )
    assert (
        await get_pdf_export(
            db_session, owner_id=other.id, report_id=report.id, export_id=export.id
        )
        is None
    )
    assert [
        item.id
        for item in await list_pdf_exports(
            db_session, owner_id=owner.id, report_id=report.id, version_id=version.id
        )
    ] == [export.id]

    restored = await restore_version_to_draft(
        db_session, owner_id=owner.id, report_id=report.id, version_id=version.id
    )
    objectives = (
        await db_session.scalars(
            select(DraftObjective)
            .where(DraftObjective.draft_id == restored.id)
            .order_by(DraftObjective.ordinal)
        )
    ).all()
    limitations = (
        await db_session.scalars(
            select(DraftLimitation).where(DraftLimitation.draft_id == restored.id)
        )
    ).all()
    narrative = (
        await db_session.scalars(
            select(DraftNarrativeItem).where(DraftNarrativeItem.draft_id == restored.id)
        )
    ).all()
    claims = (
        await db_session.scalars(select(DraftClaim).where(DraftClaim.draft_id == restored.id))
    ).all()
    assert [item.content for item in objectives] == ["Explain acquisition performance"]
    assert [item.content for item in limitations] == ["Use directional interpretation only"]
    assert [item.content for item in narrative] == ["Performance was stable."]
    assert [item.content for item in claims] == ["The campaign prioritized awareness."]
    assert (
        await db_session.scalar(
            select(func.count()).select_from(ReportVersion).where(ReportVersion.id == version.id)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_later_restore_and_export_cannot_change_snapshot_or_asset(
    db_session: AsyncSession,
) -> None:
    owner, report, draft = await seed_report(db_session, subject="version-stability")
    version_snapshot = snapshot(report.id, limitation="Original limitation")
    version = await create_report_version(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        snapshot=version_snapshot,
        snapshot_identity=report_snapshot_identity(version_snapshot),
        template_version="report-v1",
    )
    original_snapshot = dict(version.snapshot)
    original_identity = version.snapshot_identity
    await restore_version_to_draft(
        db_session, owner_id=owner.id, report_id=report.id, version_id=version.id
    )
    export = await create_pdf_export(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        version_id=version.id,
        input_identity=sha256(
            version.snapshot_identity + version.template_version.encode()
        ).digest(),
    )
    await db_session.refresh(version)
    assert version.snapshot == original_snapshot
    assert version.snapshot_identity == original_identity
    with pytest.raises(DBAPIError, match="immutable table report_versions rejects DELETE"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM report_versions WHERE id = :id"), {"id": version.id}
            )
    assert export.version_id == version.id


@pytest.mark.asyncio
async def test_all_historical_resource_groups_reject_update_and_delete(
    db_session: AsyncSession,
) -> None:
    report, dataset, _row, metric_set, _metric = await seed_dataset_metric_aggregate(
        db_session, subject="immutable-resource-groups"
    )
    draft = await db_session.scalar(
        select(ReportDraft).where(
            ReportDraft.report_id == report.id,
            ReportDraft.is_active.is_(True),
        )
    )
    assert draft is not None
    semantic_identity = sha256(b"immutable-resource-groups-analysis").digest()
    job = await create_analysis_job(
        db_session,
        owner_id=report.owner_id,
        report_id=report.id,
        semantic_input_identity=semantic_identity,
        dataset_id=dataset.id,
        metric_result_set_id=metric_set.id,
        draft_id=draft.id,
        draft_revision=draft.revision,
        objectives_revision=draft.revision,
    )
    assert await claim_analysis_job(
        db_session, owner_id=report.owner_id, report_id=report.id, job_id=job.id
    )
    result = AnalysisResult(
        owner_id=report.owner_id,
        report_id=report.id,
        job_id=job.id,
        semantic_input_identity=semantic_identity,
        model_identifier="test-model",
        prompt_version="analysis-v1",
        request_provenance="bounded computed metrics",
        numeric_source_identity=metric_set.identity,
    )
    await finish_analysis_job(
        db_session,
        owner_id=report.owner_id,
        report_id=report.id,
        job_id=job.id,
        expected_attempt_count=1,
        result=result,
        items=[
            AnalysisResultItem(
                owner_id=report.owner_id,
                report_id=report.id,
                result_id=uuid4(),
                section="summary",
                ordinal=1,
                classification="observation",
                content="CTR was unchanged.",
            )
        ],
    )
    version_snapshot = snapshot(report.id)
    await create_report_version(
        db_session,
        owner_id=report.owner_id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=draft.revision,
        snapshot=version_snapshot,
        snapshot_identity=report_snapshot_identity(version_snapshot),
        template_version="report-v1",
    )
    for table_name in (
        "file_assets",
        "report_sources",
        "import_configuration_revisions",
        "confirmed_imports",
        "canonical_datasets",
        "metric_result_sets",
        "analysis_results",
        "report_versions",
    ):
        table = Base.metadata.tables[table_name]
        for statement, operation in (
            (table.update().values(owner_id=table.c.owner_id), "UPDATE"),
            (table.delete(), "DELETE"),
        ):
            with pytest.raises(
                DBAPIError, match=rf"immutable table {table_name} rejects {operation}"
            ):
                async with db_session.begin_nested():
                    await db_session.execute(statement)


def test_snapshot_rejects_internal_storage_reference() -> None:
    data = snapshot.__annotations__
    assert "object_key" not in data
    with pytest.raises(ValidationError):
        ReportVersionSnapshot.model_validate({"object_key": "private"})
