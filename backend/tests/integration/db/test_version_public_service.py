from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
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
    create_pdf_export,
    report_snapshot_identity,
    save_draft_objectives,
)
from app.db.snapshots import ReportVersionSnapshot
from app.domain.reports import InvalidCursor, ReportNotFound
from app.domain.version_service import VersionServices
from tests.integration.db.conftest import seed_report

pytestmark = pytest.mark.postgres


def service_for(session: AsyncSession) -> VersionServices:
    assert session.bind is not None
    return VersionServices(
        async_sessionmaker(
            session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ),
        "cursor-secret-0123456789abcdef",
    )


async def confirmed_text_report(session: AsyncSession) -> tuple[Principal, Report, ReportDraft]:
    owner, report, draft = await seed_report(session, subject=str(uuid4()))
    content = "Unvalidated customer note"
    source = ReportSource(
        owner_id=owner.id,
        report_id=report.id,
        source_type="text",
        checksum_sha256=sha256(content.encode()).digest(),
        byte_size=len(content.encode()),
        media_type="text/plain",
        encoding="utf-8",
        inline_text=content,
    )
    await attach_source(session, owner_id=owner.id, report_id=report.id, source=source)
    await confirm_source_review(
        session,
        owner_id=owner.id,
        report_id=report.id,
        source_id=source.id,
        source_checksum=source.checksum_sha256,
        confirmed_by=owner.id,
    )
    return owner, report, draft


@pytest.mark.asyncio
async def test_public_version_history_restore_and_isolation(db_session: AsyncSession) -> None:
    owner, report, draft = await confirmed_text_report(db_session)
    other, other_report, _ = await seed_report(db_session, subject=str(uuid4()))
    service = service_for(db_session)
    first, replayed = await service.create(owner.id, report.id, 1, "first")
    assert not replayed and first.version_number == 1
    assert first.snapshot.source.source_type == "text"
    assert first.dataset_id is None and first.latest_pdf_export is None
    assert "inline_text" not in first.model_dump_json()
    assert "object_key" not in first.model_dump_json()
    first_record = await db_session.scalar(
        select(ReportVersion).where(ReportVersion.id == first.id)
    )
    assert first_record is not None
    export = await create_pdf_export(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        version_id=first.id,
        input_identity=sha256(
            first_record.snapshot_identity + first.template_version.encode()
        ).digest(),
    )
    await db_session.flush()
    export_summary = (await service.detail(owner.id, report.id, first.id)).latest_pdf_export
    assert export_summary is not None and export_summary.id == export.id
    repeated, replayed = await service.create(owner.id, report.id, 1, "first")
    assert replayed and repeated.id == first.id
    with pytest.raises(IdempotencyConflict):
        await service.create(owner.id, report.id, 2, "first")
    with pytest.raises(ConcurrencyConflict):
        await service.create(owner.id, report.id, 2, "stale")
    await save_draft_objectives(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        objectives=["Second objective"],
    )
    await db_session.flush()
    second, _ = await service.create(owner.id, report.id, 2, "second")
    page1, paging1 = await service.list(owner.id, report.id, 1, None)
    assert [item.id for item in page1] == [second.id]
    assert paging1.has_more and paging1.next_cursor
    await save_draft_objectives(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=2,
        objectives=["Third objective"],
    )
    await db_session.flush()
    third, _ = await service.create(owner.id, report.id, 3, "third")
    page2, paging2 = await service.list(owner.id, report.id, 1, paging1.next_cursor)
    assert [item.id for item in page2] == [first.id]
    assert not paging2.has_more
    assert (await service.detail(owner.id, report.id, first.id)).snapshot.objectives == (
        "Explain acquisition performance",
    )
    for invalid_owner, invalid_report in ((other.id, report.id), (owner.id, other_report.id)):
        with pytest.raises(InvalidCursor):
            await service.list(invalid_owner, invalid_report, 1, paging1.next_cursor)
    with pytest.raises(ReportNotFound):
        await service.list(other.id, report.id, 1, None)
    with pytest.raises(ReportNotFound):
        await service.detail(other.id, report.id, first.id)
    restored, replayed = await service.restore(
        owner.id, report.id, first.id, draft.id, 3, "restore"
    )
    assert not replayed and restored.objectives == ["Explain acquisition performance"]
    again, replayed = await service.restore(owner.id, report.id, first.id, draft.id, 3, "restore")
    assert replayed and again.id == restored.id
    original_replay, replayed = await service.create(owner.id, report.id, 1, "first")
    assert replayed and original_replay.id == first.id
    with pytest.raises(ConcurrencyConflict):
        await service.restore(owner.id, report.id, first.id, draft.id, 3, "stale-restore")
    after, _ = await service.list(owner.id, report.id, 10, None)
    assert [item.id for item in after] == [third.id, second.id, first.id]
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ReportVersion)
            .where(ReportVersion.report_id == report.id)
        )
        == 3
    )
    record = await db_session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.principal_id == owner.id,
            IdempotencyRecord.operation == "restore-version-v2",
        )
    )
    assert record is not None and record.success_status == 200


@pytest.mark.asyncio
async def test_legacy_version_read_does_not_infer_bindings(db_session: AsyncSession) -> None:
    owner, report, draft = await confirmed_text_report(db_session)
    service = service_for(db_session)
    modern, _ = await service.create(owner.id, report.id, 1, "modern")
    old_data = modern.snapshot.model_dump(
        mode="json", exclude={"dataset_id", "metric_result_set_id", "analysis_result_id", "charts"}
    )
    old_data["schema_version"] = 1
    legacy = ReportVersionSnapshot.model_validate(old_data)
    row = ReportVersion(
        owner_id=owner.id,
        report_id=report.id,
        version_number=2,
        source_draft_id=draft.id,
        source_draft_revision=1,
        template_version="report-v1",
        snapshot_schema_version=1,
        snapshot=legacy.model_dump(mode="json"),
        snapshot_identity=report_snapshot_identity(legacy),
    )
    db_session.add(row)
    await db_session.flush()
    detail = await service.detail(owner.id, report.id, row.id)
    assert detail.snapshot_schema_version == 1
    assert isinstance(detail.snapshot, ReportVersionSnapshot)
    assert detail.dataset_id is None and detail.metric_result_set_id is None
    assert detail.analysis_result_id is None
    assert "charts" not in detail.snapshot.model_dump(mode="json")
