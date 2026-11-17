from __future__ import annotations

from hashlib import sha256

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DraftChart, ReportDraft, ReportSource, ReportVersion
from app.db.repositories import (
    ConcurrencyConflict,
    IdempotencyConflict,
    attach_source,
    confirm_source_review,
    create_pdf_export,
    list_versions,
    save_draft_charts,
    save_draft_objectives,
)
from app.db.snapshots import ChartSnapshot
from app.domain.versions import restore_saved_version, save_current_report_version
from tests.integration.db.conftest import seed_report
from tests.integration.db.test_datasets_and_metrics import seed_dataset_metric_aggregate

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_save_builds_bound_schema2_and_replays(db_session: AsyncSession) -> None:
    report, dataset, _row, metric_set, metric = await seed_dataset_metric_aggregate(
        db_session, subject="saved-version-service"
    )
    owner_id = report.owner_id
    draft = (
        await db_session.scalars(select(ReportDraft).where(ReportDraft.report_id == report.id))
    ).one()
    await save_draft_charts(
        db_session,
        owner_id=owner_id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        charts=[
            ChartSnapshot(
                chart_type="bar",
                title="Click rate",
                scope="report",
                metric_result_ids=(metric.id,),
            )
        ],
    )
    first = await save_current_report_version(
        db_session,
        owner_id=owner_id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=2,
        template_version="report-v1",
        idempotency_key="first",
    )
    assert first.snapshot_schema_version == 2
    assert first.dataset_id == dataset.id
    assert first.metric_result_set_id == metric_set.id
    assert first.snapshot["metrics"][0]["metric_result_id"] == str(metric.id)
    assert first.snapshot["charts"][0]["metric_result_ids"] == [str(metric.id)]
    replay = await save_current_report_version(
        db_session,
        owner_id=owner_id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=2,
        template_version="report-v1",
        idempotency_key="first",
    )
    assert replay.id == first.id
    with pytest.raises(IdempotencyConflict):
        await save_current_report_version(
            db_session,
            owner_id=owner_id,
            report_id=report.id,
            draft_id=draft.id,
            expected_revision=2,
            template_version="report-v2",
            idempotency_key="first",
        )
    await save_draft_objectives(
        db_session,
        owner_id=owner_id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=2,
        objectives=["Revised objective"],
    )
    second = await save_current_report_version(
        db_session,
        owner_id=owner_id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=3,
        template_version="report-v1",
        idempotency_key="second",
    )
    assert second.version_number == 2
    assert first.snapshot["objectives"] == ["Explain acquisition performance"]
    assert second.snapshot["objectives"] == ["Revised objective"]
    assert [
        item.id for item in await list_versions(db_session, owner_id=owner_id, report_id=report.id)
    ] == [second.id, first.id]
    identity = sha256(first.snapshot_identity + first.template_version.encode()).digest()
    export = await create_pdf_export(
        db_session,
        owner_id=owner_id,
        report_id=report.id,
        version_id=first.id,
        input_identity=identity,
    )
    assert export.input_identity == identity
    restored = await restore_saved_version(
        db_session,
        owner_id=owner_id,
        report_id=report.id,
        version_id=first.id,
        expected_draft_id=draft.id,
        expected_revision=3,
        idempotency_key="restore-first",
    )
    assert restored.id != draft.id and restored.is_active
    assert (
        await db_session.scalars(select(DraftChart).where(DraftChart.draft_id == restored.id))
    ).one().title == "Click rate"
    replay_restored = await restore_saved_version(
        db_session,
        owner_id=owner_id,
        report_id=report.id,
        version_id=first.id,
        expected_draft_id=draft.id,
        expected_revision=3,
        idempotency_key="restore-first",
    )
    assert replay_restored.id == restored.id
    with pytest.raises(ConcurrencyConflict, match="stale"):
        await restore_saved_version(
            db_session,
            owner_id=owner_id,
            report_id=report.id,
            version_id=first.id,
            expected_draft_id=draft.id,
            expected_revision=3,
            idempotency_key="restore-again",
        )
    assert (
        await create_pdf_export(
            db_session,
            owner_id=owner_id,
            report_id=report.id,
            version_id=first.id,
            input_identity=identity,
        )
    ).id == export.id
    report.current_dataset_id = None
    report.current_metric_result_set_id = None
    await db_session.flush()
    assert (
        await create_pdf_export(
            db_session,
            owner_id=owner_id,
            report_id=report.id,
            version_id=first.id,
            input_identity=identity,
        )
    ).id == export.id
    assert first.dataset_id == dataset.id
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ReportVersion)
            .where(ReportVersion.report_id == report.id)
        )
        == 2
    )


@pytest.mark.asyncio
async def test_stale_and_foreign_bindings_do_not_create_version(db_session: AsyncSession) -> None:
    first, _dataset, _row, _set, _metric = await seed_dataset_metric_aggregate(
        db_session, subject="version-owner-first"
    )
    second, _other_dataset, _row2, _set2, _metric2 = await seed_dataset_metric_aggregate(
        db_session, subject="version-owner-second"
    )
    draft = (
        await db_session.scalars(select(ReportDraft).where(ReportDraft.report_id == first.id))
    ).one()
    with pytest.raises(ConcurrencyConflict):
        await save_current_report_version(
            db_session,
            owner_id=second.owner_id,
            report_id=first.id,
            draft_id=draft.id,
            expected_revision=1,
            template_version="report-v1",
            idempotency_key="foreign",
        )
    first.current_dataset_id = None
    await db_session.flush()
    with pytest.raises(ConcurrencyConflict, match="dataset"):
        await save_current_report_version(
            db_session,
            owner_id=first.owner_id,
            report_id=first.id,
            draft_id=draft.id,
            expected_revision=1,
            template_version="report-v1",
            idempotency_key="mismatched",
        )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ReportVersion)
            .where(ReportVersion.report_id == first.id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_confirmed_text_source_saves_without_fabricated_data(
    db_session: AsyncSession,
) -> None:
    owner, report, draft = await seed_report(db_session, subject="text-only-version")
    content = "An unvalidated user claim"
    source = ReportSource(
        owner_id=owner.id,
        report_id=report.id,
        source_type="text",
        checksum_sha256=sha256(content.encode()).digest(),
        byte_size=len(content),
        media_type="text/plain",
        encoding="utf-8",
        inline_text=content,
    )
    await attach_source(db_session, owner_id=owner.id, report_id=report.id, source=source)
    await confirm_source_review(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        source_id=source.id,
        source_checksum=source.checksum_sha256,
        confirmed_by=owner.id,
    )
    version = await save_current_report_version(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        template_version="report-v1",
        idempotency_key="text",
    )
    assert version.dataset_id is None and version.metric_result_set_id is None
    assert version.snapshot["metrics"] == []
    assert "inline_text" not in str(version.snapshot)
    other, _other_report, _ = await seed_report(db_session, subject="text-foreign")
    with pytest.raises(ConcurrencyConflict, match="unavailable"):
        await restore_saved_version(
            db_session,
            owner_id=other.id,
            report_id=report.id,
            version_id=version.id,
            expected_draft_id=draft.id,
            expected_revision=1,
            idempotency_key="foreign-restore",
        )
