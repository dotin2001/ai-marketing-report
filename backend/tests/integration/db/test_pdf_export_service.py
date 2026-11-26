"""PostgreSQL acceptance checks for PDF commands and worker attempts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest
from pypdf import PdfWriter
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.version_schemas import CreatePdfExportRequest, RetryPdfExportRequest
from app.db.models import PdfExport, PdfExportAttempt, ReportVersion
from app.db.repositories import (
    ConcurrencyConflict,
    IdempotencyConflict,
    claim_pdf_export,
    create_report_version,
    fail_pdf_export,
    report_snapshot_identity,
)
from app.domain.assets import AssetServices, ExportNotReady, ResourceNotFound
from app.domain.pdf_exports import PdfExportServices
from app.domain.reports import InvalidCursor
from app.domain.version_service import VersionServices
from app.jobs.pdf_worker import execute_pdf, fail_stale_running_pdf
from app.pdf.errors import PdfRenderFailure
from app.storage.coordinator import StorageCoordinator
from app.storage.errors import StorageErrorCode
from app.storage.fake import FakeObjectStorage
from app.storage.keys import TrustedKeyBuilder
from tests.integration.db.conftest import seed_report
from tests.integration.db.test_versions_exports_assets import snapshot

pytestmark = pytest.mark.postgres


def _sessions(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )


def _pdf(label: str = "") -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    if label:
        writer.add_metadata({"/Attempt": label})
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


async def _version(db_session: AsyncSession):
    owner, report, draft = await seed_report(db_session, subject=f"pdf-service-{uuid4()}")
    original = snapshot(report.id, limitation="Saved limitation")
    version = await create_report_version(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        snapshot=original,
        snapshot_identity=report_snapshot_identity(original),
        template_version="report-v1",
    )
    await db_session.flush()
    return owner, report, draft, version


@pytest.mark.asyncio
async def test_create_retry_idempotency_and_owner_absence(db_session: AsyncSession) -> None:
    owner, report, _draft, version = await _version(db_session)
    published: list[tuple] = []
    service = PdfExportServices(
        _sessions(db_session), "cursor-secret", publisher=lambda *x: published.append(x)
    )
    command = CreatePdfExportRequest(template_version="report-v1")
    first, replayed = await service.create(owner.id, report.id, version.id, command, "create-once")
    assert not replayed and first.state == "queued" and first.attempt_count == 1
    version_detail = await VersionServices(_sessions(db_session), "cursor-secret").detail(
        owner.id, report.id, version.id
    )
    assert version_detail.latest_pdf_export is not None
    assert version_detail.latest_pdf_export.id == first.id
    assert version_detail.latest_pdf_export.state == "queued"
    again, replayed = await service.create(owner.id, report.id, version.id, command, "create-once")
    assert replayed and again.id == first.id
    equivalent, replayed = await service.create(
        owner.id, report.id, version.id, command, "other-key"
    )
    assert not replayed and equivalent.id == first.id and len(published) == 1
    assert (await service.list(owner.id, report.id, version.id, 1, None))[0][0].id == first.id
    export_row = await db_session.scalar(select(PdfExport).where(PdfExport.id == first.id))
    assert export_row is not None
    cursor = service._encode_cursor(owner.id, report.id, version.id, export_row)
    assert (await service.list(owner.id, report.id, version.id, 1, cursor))[0] == []
    with pytest.raises(InvalidCursor):
        service._decode_cursor(owner.id, report.id, uuid4(), cursor)
    with pytest.raises(InvalidCursor):
        service._decode_cursor(owner.id, report.id, version.id, cursor + "x")
    with pytest.raises(ResourceNotFound):
        await service.detail(uuid4(), report.id, version.id, first.id)
    with pytest.raises(ResourceNotFound):
        await service.create(owner.id, report.id, uuid4(), command, "missing")
    assert await db_session.scalar(select(func.count()).select_from(ReportVersion)) == 1

    assert await claim_pdf_export(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        export_id=first.id,
        expected_attempt_count=1,
    )
    await fail_pdf_export(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        export_id=first.id,
        expected_attempt_count=1,
        failure_code="render_failed",
        failure_message="The report PDF could not be rendered.",
        retryable=True,
    )
    retry = RetryPdfExportRequest(input_identity=first.input_identity, expected_attempt_count=1)
    second, replayed = await service.retry(
        owner.id, report.id, version.id, first.id, retry, "retry-once"
    )
    assert not replayed and second.id == first.id and second.attempt_count == 2
    repeated, replayed = await service.retry(
        owner.id, report.id, version.id, first.id, retry, "retry-once"
    )
    assert replayed and repeated.attempt_count == 2
    with pytest.raises(ConcurrencyConflict):
        await service.retry(owner.id, report.id, version.id, first.id, retry, "stale")
    with pytest.raises(IdempotencyConflict):
        await service.retry(
            owner.id,
            report.id,
            version.id,
            first.id,
            RetryPdfExportRequest(input_identity=first.input_identity, expected_attempt_count=2),
            "retry-once",
        )
    assert (
        len(
            (
                await db_session.scalars(
                    select(PdfExportAttempt).where(PdfExportAttempt.export_id == first.id)
                )
            ).all()
        )
        == 2
    )


@pytest.mark.asyncio
async def test_worker_uses_saved_version_and_duplicate_delivery_is_inert(
    db_session: AsyncSession,
) -> None:
    owner, report, draft, version = await _version(db_session)
    sessions = _sessions(db_session)
    service = PdfExportServices(sessions, "cursor-secret", publisher=lambda *_: None)
    detail, _ = await service.create(
        owner.id,
        report.id,
        version.id,
        CreatePdfExportRequest(template_version="report-v1"),
        "create-worker",
    )
    draft.revision += 1
    await db_session.flush()
    fake = FakeObjectStorage()
    assets = AssetServices(
        sessions=sessions,
        coordinator=StorageCoordinator(fake),
        keys=TrustedKeyBuilder("test", "private-test"),
        source_csv_max_bytes=1024,
        generated_pdf_max_bytes=2048,
    )
    rendered: list[str] = []

    async def render(saved):
        rendered.append(saved.validated_snapshot().limitations[0])
        return _pdf()

    assert await execute_pdf(sessions, assets, owner.id, report.id, detail.id, 1, render, 2048)
    assert rendered == ["Saved limitation"]
    assert not await execute_pdf(sessions, assets, owner.id, report.id, detail.id, 1, render, 2048)
    complete = await service.detail(owner.id, report.id, version.id, detail.id)
    assert complete.state == "succeeded" and complete.file is not None
    assert complete.file.checksum == sha256(_pdf()).hexdigest()
    assert complete.file.download_available


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code", ["invalid_snapshot", "render_failed", "artifact_validation_failed", "renderer_timeout"]
)
async def test_worker_sanitizes_render_failures(
    db_session: AsyncSession,
    code: str,
) -> None:
    owner, report, _draft, version = await _version(db_session)
    sessions = _sessions(db_session)
    service = PdfExportServices(sessions, "cursor-secret", publisher=lambda *_: None)
    detail, _ = await service.create(
        owner.id,
        report.id,
        version.id,
        CreatePdfExportRequest(template_version="report-v1"),
        "create-failure",
    )
    assets = AssetServices(
        sessions=sessions,
        coordinator=StorageCoordinator(FakeObjectStorage()),
        keys=TrustedKeyBuilder("test", "private-test"),
        source_csv_max_bytes=1024,
        generated_pdf_max_bytes=2048,
    )

    async def fail(_saved):
        raise PdfRenderFailure(code)

    assert await execute_pdf(sessions, assets, owner.id, report.id, detail.id, 1, fail, 2048)
    failed = await service.detail(owner.id, report.id, version.id, detail.id)
    assert failed.state == "failed" and failed.file is None
    assert failed.failure is not None and failed.failure.code == code
    assert failed.failure.retryable == (code in {"render_failed", "renderer_timeout"})
    assert "customer" not in failed.model_dump_json()


@pytest.mark.asyncio
async def test_storage_failure_retry_uses_new_private_attempt_key(
    db_session: AsyncSession,
) -> None:
    owner, report, _draft, version = await _version(db_session)
    sessions = _sessions(db_session)
    service = PdfExportServices(sessions, "cursor-secret", publisher=lambda *_: None)
    detail, _ = await service.create(
        owner.id,
        report.id,
        version.id,
        CreatePdfExportRequest(template_version="report-v1"),
        "create-storage",
    )
    fake = FakeObjectStorage()
    fake.failures["get"] = StorageErrorCode.UNAVAILABLE
    assets = AssetServices(
        sessions=sessions,
        coordinator=StorageCoordinator(fake),
        keys=TrustedKeyBuilder("test", "private-test"),
        source_csv_max_bytes=1024,
        generated_pdf_max_bytes=2048,
    )

    async def render(_saved):
        return _pdf()

    assert await execute_pdf(sessions, assets, owner.id, report.id, detail.id, 1, render, 2048)
    failed = await service.detail(owner.id, report.id, version.id, detail.id)
    assert failed.state == "failed" and failed.file is None
    assert failed.failure is not None and failed.failure.code == "storage_unavailable"
    with pytest.raises(ExportNotReady):
        await assets.retrieve_pdf(
            owner_id=owner.id,
            report_id=report.id,
            version_id=version.id,
            export_id=detail.id,
        )
    fake.failures.clear()
    retry, _ = await service.retry(
        owner.id,
        report.id,
        version.id,
        detail.id,
        RetryPdfExportRequest(input_identity=detail.input_identity, expected_attempt_count=1),
        "retry-storage",
    )
    assert retry.attempt_count == 2

    async def render_changed(_saved):
        return _pdf("second")

    assert await execute_pdf(
        sessions, assets, owner.id, report.id, detail.id, 2, render_changed, 2048
    )
    completed = await service.detail(owner.id, report.id, version.id, detail.id)
    assert completed.state == "succeeded" and completed.file is not None
    assert len(fake._objects) == 2
    keys = [key for _, key in fake._objects]
    assert any("/attempts/1/" in key for key in keys)
    assert any("/attempts/2/" in key for key in keys)
    assert completed.file.checksum == sha256(_pdf("second")).hexdigest()
    assert await db_session.scalar(select(func.count()).select_from(ReportVersion)) == 1


@pytest.mark.asyncio
async def test_broker_recovery_and_stale_running_attempt(db_session: AsyncSession) -> None:
    owner, report, _draft, version = await _version(db_session)
    sessions = _sessions(db_session)
    published: list[tuple] = []

    def unavailable(*_args):
        raise RuntimeError("broker secret detail")

    service = PdfExportServices(sessions, "cursor-secret", publisher=unavailable)
    detail, _ = await service.create(
        owner.id,
        report.id,
        version.id,
        CreatePdfExportRequest(template_version="report-v1"),
        "create-recovery",
    )
    assert detail.state == "queued"
    service.publisher = lambda *args: published.append(args)
    assert await service.reconcile() == 1
    assert published == [(owner.id, report.id, detail.id, 1)]
    assert await claim_pdf_export(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        export_id=detail.id,
        expected_attempt_count=1,
    )
    await db_session.execute(
        update(PdfExportAttempt)
        .where(PdfExportAttempt.export_id == detail.id)
        .values(started_at=datetime.now(UTC) - timedelta(hours=1))
    )
    assert await fail_stale_running_pdf(sessions, timeout_seconds=60) == 1
    assert (await service.detail(owner.id, report.id, version.id, detail.id)).state == "failed"
    fake = FakeObjectStorage()
    assets = AssetServices(
        sessions=sessions,
        coordinator=StorageCoordinator(fake),
        keys=TrustedKeyBuilder("test", "private-test"),
        source_csv_max_bytes=1024,
        generated_pdf_max_bytes=2048,
    )

    async def render(_saved):
        return _pdf()

    assert not await execute_pdf(sessions, assets, owner.id, report.id, detail.id, 1, render, 2048)
    assert not fake._objects


@pytest.mark.asyncio
async def test_late_render_cannot_complete_timed_out_attempt(db_session: AsyncSession) -> None:
    owner, report, _draft, version = await _version(db_session)
    sessions = _sessions(db_session)
    service = PdfExportServices(sessions, "cursor-secret", publisher=lambda *_: None)
    detail, _ = await service.create(
        owner.id,
        report.id,
        version.id,
        CreatePdfExportRequest(template_version="report-v1"),
        "create-late",
    )
    fake = FakeObjectStorage()
    assets = AssetServices(
        sessions=sessions,
        coordinator=StorageCoordinator(fake),
        keys=TrustedKeyBuilder("test", "private-test"),
        source_csv_max_bytes=1024,
        generated_pdf_max_bytes=2048,
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_render(_saved):
        entered.set()
        await release.wait()
        return _pdf()

    running = asyncio.create_task(
        execute_pdf(sessions, assets, owner.id, report.id, detail.id, 1, slow_render, 2048)
    )
    await asyncio.wait_for(entered.wait(), timeout=5)
    await db_session.execute(
        update(PdfExportAttempt)
        .where(PdfExportAttempt.export_id == detail.id)
        .values(started_at=datetime.now(UTC) - timedelta(hours=1))
    )
    assert await fail_stale_running_pdf(sessions, timeout_seconds=60) == 1
    release.set()
    assert not await running
    assert (await service.detail(owner.id, report.id, version.id, detail.id)).state == "failed"
    assert not fake._objects
