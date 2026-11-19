"""Source intake against an isolated PostgreSQL transaction and deterministic storage."""

from __future__ import annotations

import asyncio
import io
import json
import os
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.models import (
    FileAsset,
    ReportDraft,
    ReportSource,
    ReportVersion,
)
from app.db.repositories import IdempotencyConflict
from app.db.testing import validate_test_database
from app.domain.assets import AssetServices, ResourceNotFound
from app.domain.reports import ReportServices
from app.domain.sources import SourceServices
from app.domain.versions import save_current_report_version
from app.processing.source_envelope import SourceEnvelopeError
from app.storage.coordinator import StorageCoordinator
from app.storage.errors import StorageError
from app.storage.fake import FakeObjectStorage
from app.storage.files import prepare_content
from app.storage.keys import TrustedKeyBuilder
from tests.integration.db.conftest import seed_report
from tests.integration.db.test_datasets_and_metrics import seed_dataset_metric_aggregate

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_text_exact_replay_conflict_and_owner_read(
    db_session: AsyncSession, settings: Settings
) -> None:
    owner, report, _ = await seed_report(db_session, subject=str(uuid4()))
    assert db_session.bind is not None
    sessions = async_sessionmaker(
        db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    fake = FakeObjectStorage()
    service = SourceServices(
        sessions,
        StorageCoordinator(fake),
        TrustedKeyBuilder(environment="test", bucket=settings.s3_bucket),
        settings,
    )
    original = " 表\t=1+1 \n"
    first, replayed = await service.attach_text(owner.id, report.id, original, "text-key")
    assert replayed is False
    assert first.byte_size == len(original.encode())
    assert first.checksum_sha256 == sha256(original.encode()).hexdigest()
    second, replayed = await service.attach_text(owner.id, report.id, original, "text-key")
    assert replayed is True and second.id == first.id
    with pytest.raises(IdempotencyConflict):
        await service.attach_text(owner.id, report.id, "changed", "text-key")
    with pytest.raises(SourceEnvelopeError):
        await service.attach_text(owner.id, report.id, "bad\x00text", "nul-key")
    preview = await service.preview(owner.id, report.id, first.id, None)  # type: ignore[arg-type]
    assert preview.excerpt == original and preview.confirmed is False
    assert fake.calls == []
    await db_session.refresh(report)
    assert report.current_source_id == first.id
    assert report.current_dataset_id is None
    assert (
        await db_session.scalar(
            select(func.count()).select_from(ReportSource).where(ReportSource.id == first.id)
        )
        == 1
    )
    with pytest.raises(ResourceNotFound):
        await service.detail(uuid4(), report.id, first.id)


@pytest.mark.asyncio
async def test_csv_exact_object_preview_replay_and_concurrency(
    db_session: AsyncSession, settings: Settings
) -> None:
    owner, report, _ = await seed_report(db_session, subject=str(uuid4()))
    assert db_session.bind is not None
    sessions = async_sessionmaker(
        db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    fake = FakeObjectStorage()
    coordinator = StorageCoordinator(fake)
    keys = TrustedKeyBuilder(environment="test", bucket=settings.s3_bucket)
    service = SourceServices(sessions, coordinator, keys, settings)
    assets = AssetServices(
        sessions=sessions,
        coordinator=coordinator,
        keys=keys,
        source_csv_max_bytes=settings.source_csv_max_bytes,
        generated_pdf_max_bytes=settings.generated_pdf_max_bytes,
    )
    original = b'\xef\xbb\xbfa,a\n"=1+1",2\nnext,3\n'
    first, replayed = await service.attach_csv(
        owner.id, report.id, original, "text/csv", "../unsafe.csv", "csv-key"
    )
    assert replayed is False
    assert first.original_filename_untrusted == "../unsafe.csv"
    assert first.display_filename == "unsafe.csv"
    verified = await assets.retrieve_csv(owner_id=owner.id, report_id=report.id, source_id=first.id)
    try:
        assert verified.file.read() == original
    finally:
        verified.close()
    preview = await service.preview(owner.id, report.id, first.id, assets)
    assert [c.ordinal for c in preview.columns or []] == [0, 1]
    assert [r.record_index for r in preview.rows or []] == [1, 2]
    assert preview.rows and preview.rows[0].values[0] == "=1+1"
    second, replayed = await service.attach_csv(
        owner.id, report.id, original, "text/csv", "../unsafe.csv", "csv-key"
    )
    assert replayed is True and second.id == first.id
    assert (
        await db_session.scalar(
            select(func.count()).select_from(FileAsset).where(FileAsset.report_id == report.id)
        )
        == 1
    )
    with pytest.raises(ResourceNotFound):
        await service.preview(owner.id, uuid4(), first.id, assets)


@pytest.mark.asyncio
async def test_csv_failure_compensates_exact_new_object_and_preserves_current(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, report, _ = await seed_report(db_session, subject=str(uuid4()))
    assert db_session.bind is not None
    sessions = async_sessionmaker(
        db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    fake = FakeObjectStorage()
    service = SourceServices(
        sessions,
        StorageCoordinator(fake),
        TrustedKeyBuilder(environment="test", bucket=settings.s3_bucket),
        settings,
    )
    before, _ = await service.attach_text(owner.id, report.id, "original", "before")

    async def fail_attach(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated transaction failure")

    monkeypatch.setattr("app.domain.sources.attach_source", fail_attach)
    with pytest.raises(RuntimeError, match="simulated transaction failure"):
        await service.attach_csv(owner.id, report.id, b"a,b\n1,2\n", "text/csv", "x.csv", "failed")
    await db_session.refresh(report)
    assert report.current_source_id == before.id
    assert fake._objects == {}


@pytest.mark.asyncio
async def test_corrupted_csv_preview_fails_closed(
    db_session: AsyncSession, settings: Settings
) -> None:
    owner, report, _ = await seed_report(db_session, subject=str(uuid4()))
    assert db_session.bind is not None
    sessions = async_sessionmaker(
        db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    fake = FakeObjectStorage()
    coordinator = StorageCoordinator(fake)
    keys = TrustedKeyBuilder(environment="test", bucket=settings.s3_bucket)
    service = SourceServices(sessions, coordinator, keys, settings)
    assets = AssetServices(
        sessions=sessions,
        coordinator=coordinator,
        keys=keys,
        source_csv_max_bytes=settings.source_csv_max_bytes,
        generated_pdf_max_bytes=settings.generated_pdf_max_bytes,
    )
    detail, _ = await service.attach_csv(
        owner.id, report.id, b"a,b\n1,2\n", "text/csv", "x.csv", "corrupt"
    )
    fake.corrupt(
        keys.source_csv(owner_id=owner.id, report_id=report.id, source_id=detail.id), b"changed"
    )
    with pytest.raises(StorageError):
        await service.preview(owner.id, report.id, detail.id, assets)


@pytest.mark.asyncio
async def test_crash_orphan_is_verified_and_reused(
    db_session: AsyncSession, settings: Settings
) -> None:
    owner, report, _ = await seed_report(db_session, subject=str(uuid4()))
    assert db_session.bind is not None
    sessions = async_sessionmaker(
        db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    fake = FakeObjectStorage()
    coordinator = StorageCoordinator(fake)
    keys = TrustedKeyBuilder(environment="test", bucket=settings.s3_bucket)
    service = SourceServices(sessions, coordinator, keys, settings)
    original = b"a,b\n1,2\n"
    fingerprint = sha256(
        json.dumps([sha256(original).hexdigest(), "text/csv", "x.csv"]).encode()
    ).digest()
    record_id = await service._reserve(
        owner.id, report.id, "attach-source-csv", "orphan", fingerprint
    )
    source_id = uuid5(NAMESPACE_URL, str(record_id))
    prepared = await prepare_content(
        io.BytesIO(original),
        identity=keys.source_csv(owner_id=owner.id, report_id=report.id, source_id=source_id),
        owner_id=owner.id,
        report_id=report.id,
        logical_id=source_id,
        safe_filename="x.csv",
        content_type="text/csv",
        max_bytes=settings.source_csv_max_bytes,
    )
    try:
        await coordinator.create_or_verify(prepared)
    finally:
        prepared.close()
    put_count = fake.calls.count("put_if_absent")
    detail, replayed = await service.attach_csv(
        owner.id, report.id, original, "text/csv", "x.csv", "orphan"
    )
    assert replayed is False and detail.id == source_id
    assert fake.calls.count("put_if_absent") == put_count


@pytest.mark.asyncio
async def test_new_source_invalidates_current_metrics_but_preserves_prior_source(
    db_session: AsyncSession, settings: Settings
) -> None:
    report, dataset, _row, metric_set, _metric = await seed_dataset_metric_aggregate(
        db_session, subject=str(uuid4())
    )
    await db_session.flush()
    await db_session.refresh(report)
    previous = report.current_source_id
    assert previous is not None
    draft = await db_session.scalar(select(ReportDraft).where(ReportDraft.report_id == report.id))
    assert draft is not None
    version = await save_current_report_version(
        db_session,
        owner_id=report.owner_id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=draft.revision,
        template_version="report-v1",
        idempotency_key="before-source",
    )
    await db_session.flush()
    assert db_session.bind is not None
    sessions = async_sessionmaker(
        db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    fake = FakeObjectStorage()
    service = SourceServices(
        sessions,
        StorageCoordinator(fake),
        TrustedKeyBuilder(environment="test", bucket=settings.s3_bucket),
        settings,
    )
    added, _ = await service.attach_text(report.owner_id, report.id, "new source", "replace")
    await db_session.refresh(report)
    assert report.current_source_id == added.id
    assert report.current_dataset_id is None
    assert report.current_metric_result_set_id is None
    assert report.current_analysis_result_id is None
    assert await db_session.get(ReportSource, previous) is not None
    assert await db_session.get(type(dataset), dataset.id) is not None
    assert await db_session.get(type(metric_set), metric_set.id) is not None
    assert await db_session.get(ReportVersion, version.id) is not None
    assert (
        await ReportServices(sessions, "x" * 32).detail(report.owner_id, report.id)
    ).stage == "source_review"


@pytest.mark.asyncio
async def test_same_key_concurrent_text_requests_converge(
    settings: Settings,
) -> None:
    target = validate_test_database(
        app_env=os.environ.get("APP_ENV"),
        test_database_url=os.environ.get("TEST_DATABASE_URL"),
        database_url=os.environ.get("DATABASE_URL"),
    )
    engine = create_async_engine(target.url, pool_pre_ping=False)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session, session.begin():
        owner, report, _ = await seed_report(session, subject=str(uuid4()))
        owner_id, report_id = owner.id, report.id
    service = SourceServices(
        sessions,
        StorageCoordinator(FakeObjectStorage()),
        TrustedKeyBuilder(environment="test", bucket=settings.s3_bucket),
        settings,
    )
    try:
        results = await asyncio.gather(
            *[service.attach_text(owner_id, report_id, "same", "concurrent") for _ in range(2)]
        )
        assert results[0][0].id == results[1][0].id
        assert sorted(replayed for _, replayed in results) == [False, True]
        csv_results = await asyncio.gather(
            *[
                service.attach_csv(
                    owner_id, report_id, b"a,b\n1,2\n", "text/csv", "x.csv", "csv-concurrent"
                )
                for _ in range(2)
            ]
        )
        assert csv_results[0][0].id == csv_results[1][0].id
        assert sorted(replayed for _, replayed in csv_results) == [False, True]
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ReportSource)
                    .where(ReportSource.report_id == report_id)
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FileAsset)
                    .where(FileAsset.report_id == report_id)
                )
                == 1
            )
    finally:
        # Immutable-source triggers prohibit cleanup; this case uses only a guarded _test database.
        await engine.dispose()
