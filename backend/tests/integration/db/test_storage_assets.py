from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.domain.assets as asset_module
from app.db.models import FileAsset, PdfExport, Principal, Report, ReportSource, ReportVersion
from app.db.repositories import (
    ConcurrencyConflict,
    claim_pdf_export,
    create_pdf_export,
    create_report_version,
    get_pdf_asset,
    get_source_asset,
    report_snapshot_identity,
)
from app.db.snapshots import ReportVersionSnapshot
from app.domain.assets import AssetServices, ResourceNotFound
from app.storage.coordinator import StorageCoordinator
from app.storage.errors import StorageError, StorageErrorCode
from app.storage.fake import FakeObjectStorage
from app.storage.keys import TrustedKeyBuilder
from app.storage.types import ObjectMetadata
from tests.integration.db.conftest import seed_report
from tests.integration.db.test_versions_exports_assets import snapshot

pytestmark = pytest.mark.postgres


def services_for(
    db_session: AsyncSession,
    fake: FakeObjectStorage,
) -> AssetServices:
    return AssetServices(
        sessions=async_sessionmaker(
            bind=db_session.bind,
            expire_on_commit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        ),
        coordinator=StorageCoordinator(fake),
        keys=TrustedKeyBuilder(environment="test", bucket="private-test"),
        source_csv_max_bytes=1024,
        generated_pdf_max_bytes=2048,
    )


async def seeded_export(
    db_session: AsyncSession,
) -> tuple[Principal, Report, ReportVersion, PdfExport, bytes]:
    owner, report, draft = await seed_report(db_session, subject=f"storage-{uuid4()}")
    version_snapshot: ReportVersionSnapshot = snapshot(report.id)
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
    assert await claim_pdf_export(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        export_id=export.id,
    )
    await db_session.flush()
    return owner, report, version, export, input_identity


@pytest.mark.asyncio
async def test_csv_service_binds_one_asset_retries_exactly_and_retrieves(
    db_session: AsyncSession,
) -> None:
    owner, report, _draft = await seed_report(db_session, subject="storage-csv-owner")
    await db_session.flush()
    fake = FakeObjectStorage()
    service = services_for(db_session, fake)
    source_id = uuid4()
    csv = b"date,campaign_name,currency\n2026-01-01,A,USD\n"
    first = await service.store_csv(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source_id,
        original_filename="../../campaign.csv",
        content=BytesIO(csv),
    )
    replay = await service.store_csv(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source_id,
        original_filename="../../campaign.csv",
        content=BytesIO(csv),
    )
    assert replay.source.id == first.source.id
    assert replay.asset.id == first.asset.id
    assert replay.asset.object_key.startswith(f"v1/test/owners/{owner.id}/reports/{report.id}/")
    assert replay.source.display_filename == "campaign.csv"
    assert (
        await db_session.scalar(
            select(func.count()).select_from(ReportSource).where(ReportSource.id == source_id)
        )
        == 1
    )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(FileAsset).where(FileAsset.report_id == report.id)
        )
        == 1
    )
    downloaded = await service.retrieve_csv(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source_id,
    )
    assert downloaded.file.read() == csv
    downloaded.close()


@pytest.mark.asyncio
async def test_csv_collision_failure_and_cross_owner_lookup_never_adopt_or_fetch(
    db_session: AsyncSession,
) -> None:
    owner, report, _draft = await seed_report(db_session, subject="storage-csv-collision")
    other, _other_report, _other_draft = await seed_report(db_session, subject="storage-csv-other")
    await db_session.flush()
    fake = FakeObjectStorage()
    service = services_for(db_session, fake)
    source_id = uuid4()
    await service.store_csv(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source_id,
        original_filename="source.csv",
        content=BytesIO(b"a,b\n1,2\n"),
    )
    with pytest.raises(StorageError) as collision:
        await service.store_csv(
            owner_id=owner.id,
            report_id=report.id,
            source_id=source_id,
            original_filename="source.csv",
            content=BytesIO(b"a,b\n3,4\n"),
        )
    assert collision.value.code is StorageErrorCode.COLLISION
    calls_before = list(fake.calls)
    with pytest.raises(ResourceNotFound):
        await service.retrieve_csv(
            owner_id=other.id,
            report_id=report.id,
            source_id=source_id,
        )
    assert fake.calls == calls_before
    assert (
        await get_source_asset(
            db_session,
            owner_id=other.id,
            report_id=report.id,
            source_id=source_id,
        )
        is None
    )


@pytest.mark.asyncio
async def test_csv_retrieval_rejects_tampering_without_partial_content(
    db_session: AsyncSession,
) -> None:
    owner, report, _draft = await seed_report(db_session, subject="storage-csv-tamper")
    await db_session.flush()
    fake = FakeObjectStorage()
    service = services_for(db_session, fake)
    source_id = uuid4()
    aggregate = await service.store_csv(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source_id,
        original_filename="source.csv",
        content=BytesIO(b"a,b\n1,2\n"),
    )
    identity = TrustedKeyBuilder(environment="test", bucket="private-test").source_csv(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source_id,
    )
    fake.corrupt(identity, b"partial")
    with pytest.raises(StorageError) as integrity:
        await service.retrieve_csv(
            owner_id=owner.id,
            report_id=report.id,
            source_id=source_id,
        )
    assert aggregate.asset.checksum_sha256 != sha256(b"partial").digest()
    assert integrity.value.code is StorageErrorCode.INTEGRITY_FAILED


@pytest.mark.asyncio
async def test_csv_database_failure_compensates_only_new_object(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, report, _draft = await seed_report(db_session, subject="storage-csv-rollback")
    await db_session.flush()
    fake = FakeObjectStorage()
    service = services_for(db_session, fake)
    source_id = uuid4()

    async def fail_binding(*_: object, **__: object) -> object:
        raise RuntimeError("forced database failure")

    monkeypatch.setattr(asset_module, "insert_or_load_csv_binding", fail_binding)
    with pytest.raises(RuntimeError, match="forced database failure"):
        await service.store_csv(
            owner_id=owner.id,
            report_id=report.id,
            source_id=source_id,
            original_filename="source.csv",
            content=BytesIO(b"a,b\n1,2\n"),
        )
    identity = TrustedKeyBuilder(environment="test", bucket="private-test").source_csv(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source_id,
    )
    assert await fake.head(identity) is None
    assert (
        await db_session.scalar(
            select(func.count()).select_from(FileAsset).where(FileAsset.report_id == report.id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_csv_uncertain_commit_reconciles_durable_exact_binding_before_compensation(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, report, _draft = await seed_report(db_session, subject="storage-csv-uncertain")
    await db_session.flush()
    fake = FakeObjectStorage()
    service = services_for(db_session, fake)
    source_id = uuid4()
    csv = b"a,b\n1,2\n"
    committed = await service.store_csv(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source_id,
        original_filename="source.csv",
        content=BytesIO(csv),
    )
    identity = TrustedKeyBuilder(environment="test", bucket="private-test").source_csv(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source_id,
    )
    metadata = ObjectMetadata(
        identity=identity,
        owner_id=owner.id,
        report_id=report.id,
        logical_id=source_id,
        content_type="text/csv",
        byte_size=len(csv),
        checksum_sha256=sha256(csv).hexdigest(),
    )
    assert await fake.delete_exact(metadata, created_by_invocation=True)

    async def uncertain_commit(*_: object, **__: object) -> object:
        raise RuntimeError("commit outcome was uncertain")

    monkeypatch.setattr(asset_module, "insert_or_load_csv_binding", uncertain_commit)
    reconciled = await service.store_csv(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source_id,
        original_filename="source.csv",
        content=BytesIO(csv),
    )
    assert reconciled.asset.id == committed.asset.id
    assert await fake.head(identity) == metadata


@pytest.mark.asyncio
async def test_pdf_service_completes_matching_export_and_exact_retry_keeps_one_version(
    db_session: AsyncSession,
) -> None:
    owner, report, version, export, input_identity = await seeded_export(db_session)
    owner_id = owner.id
    report_id = report.id
    version_id = version.id
    export_id = export.id
    fake = FakeObjectStorage()
    service = services_for(db_session, fake)
    pdf = b"%PDF-1.7\nverified"
    first = await service.store_generated_pdf(
        owner_id=owner_id,
        report_id=report_id,
        version_id=version_id,
        export_id=export_id,
        input_identity=input_identity,
        expected_attempt_count=1,
        content=BytesIO(pdf),
    )
    replay = await service.store_generated_pdf(
        owner_id=owner_id,
        report_id=report_id,
        version_id=version_id,
        export_id=export_id,
        input_identity=input_identity,
        expected_attempt_count=1,
        content=BytesIO(pdf),
    )
    assert replay.id == first.id
    db_session.expire_all()
    aggregate = await get_pdf_asset(
        db_session,
        owner_id=owner_id,
        report_id=report_id,
        version_id=version_id,
        export_id=export_id,
    )
    assert aggregate is not None and aggregate.export.state == "succeeded"
    assert aggregate.asset is not None and aggregate.asset.id == first.id
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ReportVersion)
            .where(ReportVersion.report_id == report_id)
        )
        == 1
    )
    downloaded = await service.retrieve_pdf(
        owner_id=owner_id,
        report_id=report_id,
        version_id=version_id,
        export_id=export_id,
    )
    assert downloaded.file.read() == pdf
    downloaded.close()


@pytest.mark.asyncio
async def test_pdf_service_rejects_stale_input_before_storage(
    db_session: AsyncSession,
) -> None:
    owner, report, version, export, _input_identity = await seeded_export(db_session)
    fake = FakeObjectStorage()
    service = services_for(db_session, fake)
    with pytest.raises(ConcurrencyConflict, match="input identity is stale"):
        await service.store_generated_pdf(
            owner_id=owner.id,
            report_id=report.id,
            version_id=version.id,
            export_id=export.id,
            input_identity=b"x" * 32,
            expected_attempt_count=1,
            content=BytesIO(b"%PDF-1.7\nwrong"),
        )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_pdf_storage_and_database_failures_do_not_complete_or_rebind_export(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, report, version, export, input_identity = await seeded_export(db_session)
    fake = FakeObjectStorage()
    service = services_for(db_session, fake)
    fake.failures["head"] = StorageErrorCode.UNAVAILABLE
    with pytest.raises(StorageError) as unavailable:
        await service.store_generated_pdf(
            owner_id=owner.id,
            report_id=report.id,
            version_id=version.id,
            export_id=export.id,
            input_identity=input_identity,
            expected_attempt_count=1,
            content=BytesIO(b"%PDF-1.7\nunavailable"),
        )
    assert unavailable.value.code is StorageErrorCode.UNAVAILABLE
    fake.failures.clear()

    async def fail_completion(*_: object, **__: object) -> FileAsset:
        raise RuntimeError("forced PDF database failure")

    monkeypatch.setattr(asset_module, "finish_pdf_export", fail_completion)
    with pytest.raises(RuntimeError, match="forced PDF database failure"):
        await service.store_generated_pdf(
            owner_id=owner.id,
            report_id=report.id,
            version_id=version.id,
            export_id=export.id,
            input_identity=input_identity,
            expected_attempt_count=1,
            content=BytesIO(b"%PDF-1.7\nrollback"),
        )
    identity = TrustedKeyBuilder(environment="test", bucket="private-test").generated_pdf(
        owner_id=owner.id,
        report_id=report.id,
        version_id=version.id,
        export_id=export.id,
    )
    assert await fake.head(identity) is None
    await db_session.refresh(export)
    assert export.state == "running" and export.generated_asset_id is None


@pytest.mark.asyncio
async def test_pdf_cross_version_lookup_and_tampered_retrieval_fail_closed(
    db_session: AsyncSession,
) -> None:
    owner, report, version, export, input_identity = await seeded_export(db_session)
    fake = FakeObjectStorage()
    service = services_for(db_session, fake)
    with pytest.raises(ResourceNotFound):
        await service.store_generated_pdf(
            owner_id=owner.id,
            report_id=report.id,
            version_id=uuid4(),
            export_id=export.id,
            input_identity=input_identity,
            expected_attempt_count=1,
            content=BytesIO(b"%PDF-1.7\nwrong-version"),
        )
    assert fake.calls == []

    await service.store_generated_pdf(
        owner_id=owner.id,
        report_id=report.id,
        version_id=version.id,
        export_id=export.id,
        input_identity=input_identity,
        expected_attempt_count=1,
        content=BytesIO(b"%PDF-1.7\nverified"),
    )
    identity = TrustedKeyBuilder(environment="test", bucket="private-test").generated_pdf(
        owner_id=owner.id,
        report_id=report.id,
        version_id=version.id,
        export_id=export.id,
    )
    fake.corrupt(identity, b"%PDF-partial")
    with pytest.raises(StorageError) as integrity:
        await service.retrieve_pdf(
            owner_id=owner.id,
            report_id=report.id,
            version_id=version.id,
            export_id=export.id,
        )
    assert integrity.value.code is StorageErrorCode.INTEGRITY_FAILED


@pytest.mark.asyncio
async def test_pdf_uncertain_commit_reconciles_matching_asset(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, report, version, export, input_identity = await seeded_export(db_session)
    fake = FakeObjectStorage()
    service = services_for(db_session, fake)
    data = b"%PDF-1.7\nverified"
    committed = await service.store_generated_pdf(
        owner_id=owner.id,
        report_id=report.id,
        version_id=version.id,
        export_id=export.id,
        input_identity=input_identity,
        expected_attempt_count=1,
        content=BytesIO(data),
    )
    identity = TrustedKeyBuilder(environment="test", bucket="private-test").generated_pdf(
        owner_id=owner.id,
        report_id=report.id,
        version_id=version.id,
        export_id=export.id,
        attempt_ordinal=1,
    )
    metadata = ObjectMetadata(
        identity=identity,
        owner_id=owner.id,
        report_id=report.id,
        logical_id=export.id,
        content_type="application/pdf",
        byte_size=len(data),
        checksum_sha256=sha256(data).hexdigest(),
    )
    assert await fake.delete_exact(metadata, created_by_invocation=True)

    async def uncertain_commit(*_: object, **__: object) -> FileAsset:
        raise RuntimeError("commit outcome was uncertain")

    monkeypatch.setattr(asset_module, "finish_pdf_export", uncertain_commit)
    reconciled = await service.store_generated_pdf(
        owner_id=owner.id,
        report_id=report.id,
        version_id=version.id,
        export_id=export.id,
        input_identity=input_identity,
        expected_attempt_count=1,
        content=BytesIO(data),
    )
    assert reconciled.id == committed.id
    assert await fake.head(identity) == metadata
