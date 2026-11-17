from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import boto3
import pytest
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import (
    AuthenticatedPrincipal,
    get_asset_services,
    get_authenticated_principal,
)
from app.core.config import Settings
from app.db.models import FileAsset
from app.db.repositories import get_pdf_asset, get_source_asset
from app.db.testing import validate_test_database
from app.domain.assets import AssetServices
from app.main import create_app
from app.storage.coordinator import StorageCoordinator
from app.storage.errors import StorageError, StorageErrorCode
from app.storage.files import prepare_content
from app.storage.keys import TrustedKeyBuilder
from app.storage.s3 import S3ObjectStorage
from app.storage.types import ObjectIdentity, ObjectMetadata
from tests.integration.db.conftest import seed_report
from tests.integration.db.test_storage_assets import seeded_export

pytestmark = [pytest.mark.storage_live, pytest.mark.postgres]


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} is required for the opted-in live storage suite")
    return value


@pytest.fixture
def live_settings() -> Iterator[dict[str, str]]:
    if os.environ.get("RUN_STORAGE_LIVE") != "1":
        pytest.skip("set RUN_STORAGE_LIVE=1 with test-scoped storage configuration")
    if os.environ.get("APP_ENV") != "test":
        pytest.fail("APP_ENV must be test for live storage cleanup")
    bucket = required("S3_BUCKET")
    if "test" not in bucket:
        pytest.fail("S3_BUCKET must be visibly test-scoped")
    settings = {
        "endpoint": required("S3_ENDPOINT_URL"),
        "region": required("S3_REGION"),
        "access_key": required("S3_ACCESS_KEY_ID"),
        "secret_key": required("S3_SECRET_ACCESS_KEY"),
        "bucket": bucket,
    }
    signed = client(settings)
    existing = {item["Name"] for item in signed.list_buckets().get("Buckets", [])}
    created_bucket = bucket not in existing
    if created_bucket:
        signed.create_bucket(Bucket=bucket)
    try:
        yield settings
    finally:
        if created_bucket:
            signed.delete_bucket(Bucket=bucket)


def client(settings: dict[str, str], *, unsigned: bool = False) -> Any:
    config_values: dict[str, object] = {
        "connect_timeout": 5,
        "read_timeout": 5,
        "retries": {"max_attempts": 2, "mode": "standard"},
        "s3": {"addressing_style": "path"},
    }
    if unsigned:
        config_values["signature_version"] = UNSIGNED
    config = Config(
        **config_values,
    )
    return boto3.client(
        "s3",
        endpoint_url=settings["endpoint"],
        region_name=settings["region"],
        aws_access_key_id=None if unsigned else settings["access_key"],
        aws_secret_access_key=None if unsigned else settings["secret_key"],
        use_ssl=settings["endpoint"].startswith("https://"),
        config=config,
    )


@pytest.fixture
async def live_db_session() -> AsyncIterator[AsyncSession]:
    target = validate_test_database(
        app_env=os.environ.get("APP_ENV"),
        test_database_url=os.environ.get("TEST_DATABASE_URL"),
        database_url=os.environ.get("DATABASE_URL"),
    )
    engine = create_async_engine(target.url, pool_pre_ping=False)
    async with engine.connect() as connection:
        outer = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()
    await engine.dispose()


def persisted_metadata(
    asset: FileAsset,
    *,
    identity: ObjectIdentity,
    logical_id: UUID,
) -> ObjectMetadata:
    return ObjectMetadata(
        identity=identity,
        owner_id=asset.owner_id,
        report_id=asset.report_id,
        logical_id=logical_id,
        content_type=asset.content_type,
        byte_size=asset.byte_size,
        checksum_sha256=asset.checksum_sha256.hex(),
    )


@pytest.mark.asyncio
async def test_private_conditional_csv_pdf_round_trips_and_exact_cleanup(
    live_settings: dict[str, str],
) -> None:
    signed = client(live_settings)
    adapter = S3ObjectStorage(signed)
    coordinator = StorageCoordinator(adapter)
    keys = TrustedKeyBuilder(environment="test", bucket=live_settings["bucket"])
    owner_id, report_id, source_id, version_id, export_id = (uuid4() for _ in range(5))
    csv = await prepare_content(
        BytesIO(b"date,campaign_name,currency\n2026-01-01,A,USD\n"),
        identity=keys.source_csv(
            owner_id=owner_id,
            report_id=report_id,
            source_id=source_id,
        ),
        owner_id=owner_id,
        report_id=report_id,
        logical_id=source_id,
        safe_filename="source.csv",
        content_type="text/csv",
        max_bytes=1024,
    )
    pdf = await prepare_content(
        BytesIO(b"%PDF-1.7\nlive"),
        identity=keys.generated_pdf(
            owner_id=owner_id,
            report_id=report_id,
            version_id=version_id,
            export_id=export_id,
        ),
        owner_id=owner_id,
        report_id=report_id,
        logical_id=export_id,
        safe_filename="report-1.pdf",
        content_type="application/pdf",
        max_bytes=1024,
    )
    created = []
    try:
        for prepared in (csv, pdf):
            result = await coordinator.create_or_verify(prepared)
            created.append(result)
            assert result.created
            replay = await coordinator.create_or_verify(prepared)
            assert not replay.created
            retrieved = await coordinator.retrieve_verified(
                expected=prepared.metadata,
                safe_filename=prepared.safe_filename,
                max_bytes=prepared.metadata.byte_size,
            )
            prepared.file.seek(0)
            assert retrieved.file.read() == prepared.file.read()
            retrieved.close()

        conflicting = await prepare_content(
            BytesIO(b"different"),
            identity=csv.metadata.identity,
            owner_id=owner_id,
            report_id=report_id,
            logical_id=source_id,
            safe_filename="source.csv",
            content_type="text/csv",
            max_bytes=1024,
        )
        try:
            with pytest.raises(StorageError) as collision:
                await coordinator.create_or_verify(conflicting)
            assert collision.value.code is StorageErrorCode.COLLISION
        finally:
            conflicting.close()

        anonymous = client(live_settings, unsigned=True)
        with pytest.raises(ClientError):
            anonymous.get_object(
                Bucket=live_settings["bucket"],
                Key=csv.metadata.identity.key,
            )
        with pytest.raises(ClientError):
            anonymous.list_objects_v2(Bucket=live_settings["bucket"], Prefix="v1/test/")
    finally:
        assert all(item.metadata.identity.key.startswith("v1/test/") for item in created)
        for item in reversed(created):
            assert await adapter.delete_exact(item.metadata, created_by_invocation=True)
        csv.close()
        pdf.close()


@pytest.mark.asyncio
async def test_live_persistence_owner_denial_and_authorized_pdf_stream(
    live_settings: dict[str, str],
    live_db_session: AsyncSession,
    settings: Settings,
) -> None:
    signed = client(live_settings)
    adapter = S3ObjectStorage(signed)
    coordinator = StorageCoordinator(adapter)
    keys = TrustedKeyBuilder(environment="test", bucket=live_settings["bucket"])
    sessions = async_sessionmaker(
        bind=live_db_session.bind,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    services = AssetServices(
        sessions=sessions,
        coordinator=coordinator,
        keys=keys,
        source_csv_max_bytes=1024,
        generated_pdf_max_bytes=2048,
    )
    owner, report, version, export, input_identity = await seeded_export(live_db_session)
    owner_id = owner.id
    report_id = report.id
    version_id = version.id
    export_id = export.id
    source_id = uuid4()
    csv_bytes = b"date,campaign_name,currency\n2026-01-01,Live,USD\n"
    pdf_bytes = b"%PDF-1.7\nlive-authorized"
    created: list[ObjectMetadata] = []
    try:
        csv_result = await services.store_csv(
            owner_id=owner_id,
            report_id=report_id,
            source_id=source_id,
            original_filename="live.csv",
            content=BytesIO(csv_bytes),
        )
        csv_metadata = persisted_metadata(
            csv_result.asset,
            identity=keys.source_csv(
                owner_id=owner_id,
                report_id=report_id,
                source_id=source_id,
            ),
            logical_id=source_id,
        )
        created.append(csv_metadata)
        pdf_asset = await services.store_generated_pdf(
            owner_id=owner_id,
            report_id=report_id,
            version_id=version_id,
            export_id=export_id,
            input_identity=input_identity,
            expected_attempt_count=1,
            content=BytesIO(pdf_bytes),
        )
        pdf_metadata = persisted_metadata(
            pdf_asset,
            identity=keys.generated_pdf(
                owner_id=owner_id,
                report_id=report_id,
                version_id=version_id,
                export_id=export_id,
            ),
            logical_id=export_id,
        )
        created.append(pdf_metadata)

        live_db_session.expire_all()
        source_aggregate = await get_source_asset(
            live_db_session,
            owner_id=owner_id,
            report_id=report_id,
            source_id=source_id,
        )
        pdf_aggregate = await get_pdf_asset(
            live_db_session,
            owner_id=owner_id,
            report_id=report_id,
            version_id=version_id,
            export_id=export_id,
        )
        assert source_aggregate is not None
        assert source_aggregate.asset.object_key == csv_metadata.identity.key
        assert pdf_aggregate is not None and pdf_aggregate.asset is not None
        assert pdf_aggregate.export.state == "succeeded"
        assert pdf_aggregate.asset.object_key == pdf_metadata.identity.key

        app = create_app(settings)
        app.dependency_overrides[get_asset_services] = lambda: services
        app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(
            id=owner_id
        )
        route = (
            f"/api/v1/reports/{report_id}/versions/{version_id}/pdf-exports/{export_id}/download"
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as http:
            response = await http.get(route)
            assert response.status_code == 200
            assert response.content == pdf_bytes
            assert response.headers["content-type"] == "application/pdf"
            assert response.headers["cache-control"] == "private, no-store"

            other, _other_report, _other_draft = await seed_report(
                live_db_session,
                subject=f"live-other-{uuid4()}",
            )
            await live_db_session.flush()
            app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(
                id=other.id
            )
            denied = await http.get(route)
            assert denied.status_code == 404
            assert denied.json()["error"]["code"] == "resource_not_found"
    finally:
        assert all(item.identity.key.startswith("v1/test/") for item in created)
        for metadata in reversed(created):
            assert await adapter.delete_exact(metadata, created_by_invocation=True)
