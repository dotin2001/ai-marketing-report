"""Import review against isolated PostgreSQL and verified fake object storage."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.source_schemas import (
    ColumnMapping,
    ImportConfigurationRequest,
    ValidateImportRequest,
)
from app.core.config import Settings
from app.db.models import ConfirmedImport, ImportValidation, MetricResultSet, Report
from app.db.repositories import ConcurrencyConflict
from app.domain.assets import AssetServices, ResourceNotFound
from app.domain.import_review import ImportReviewServices, InvalidMapping
from app.domain.sources import SourceServices
from app.storage.coordinator import StorageCoordinator
from app.storage.fake import FakeObjectStorage
from app.storage.keys import TrustedKeyBuilder
from tests.integration.db.conftest import seed_report

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_review_persists_exact_revision_and_keeps_downstream_empty(
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    owner, report, _ = await seed_report(db_session, subject=str(uuid4()))
    assert db_session.bind is not None
    sessions = async_sessionmaker(
        db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    coordinator = StorageCoordinator(FakeObjectStorage())
    keys = TrustedKeyBuilder(environment="test", bucket=settings.s3_bucket)
    sources = SourceServices(sessions, coordinator, keys, settings)
    assets = AssetServices(
        sessions=sessions,
        coordinator=coordinator,
        keys=keys,
        source_csv_max_bytes=settings.source_csv_max_bytes,
        generated_pdf_max_bytes=settings.generated_pdf_max_bytes,
    )
    review = ImportReviewServices(sessions, settings)
    original = b"date,campaign,currency,clicks\n2026-01-01,A,USD,1\n2026-01-02,B,USD,bad\n"
    source, _ = await sources.attach_csv(
        owner.id, report.id, original, "text/csv", "test.csv", "import-review-1"
    )
    command = ImportConfigurationRequest(
        expected_revision=0,
        normalization_policy_version="normalize-v1",
        mappings=[
            ColumnMapping(source_column_ordinal=0, canonical_field="date"),
            ColumnMapping(source_column_ordinal=1, canonical_field="campaign_name"),
            ColumnMapping(source_column_ordinal=2, canonical_field="currency"),
            ColumnMapping(source_column_ordinal=3, canonical_field="clicks"),
        ],
    )
    config = await review.put_configuration(owner.id, report.id, source.id, command, assets)
    assert config.revision == 1
    with pytest.raises(ConcurrencyConflict):
        await review.put_configuration(owner.id, report.id, source.id, command, assets)
    result = await review.validate(
        owner.id, report.id, source.id, ValidateImportRequest(expected_revision=1), assets
    )
    assert result.confirmation_blocked is True
    assert (result.error_count, result.warning_count, result.total_records) == (1, 0, 2)
    assert [
        (item.code, item.source_record_index, item.source_column_ordinal) for item in result.issues
    ] == [("invalid_count", 2, 3)]
    repeated = await review.validate(
        owner.id, report.id, source.id, ValidateImportRequest(expected_revision=1), assets
    )
    assert repeated.id == result.id
    assert await db_session.scalar(select(func.count()).select_from(ImportValidation)) == 1
    assert await db_session.scalar(select(func.count()).select_from(ConfirmedImport)) == 0
    assert await db_session.scalar(select(func.count()).select_from(MetricResultSet)) == 0
    with pytest.raises(ResourceNotFound):
        await review.validate(
            uuid4(), report.id, source.id, ValidateImportRequest(expected_revision=1), assets
        )
    with pytest.raises(InvalidMapping):
        await review.put_configuration(
            owner.id,
            report.id,
            source.id,
            command.model_copy(
                update={
                    "expected_revision": 1,
                    "mappings": [ColumnMapping(source_column_ordinal=9, canonical_field="date")],
                }
            ),
            assets,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["period", "source"])
async def test_validation_rejects_changed_input_before_persisting(
    db_session: AsyncSession,
    settings: Settings,
    race: str,
) -> None:
    owner, report, _ = await seed_report(db_session, subject=str(uuid4()))
    assert db_session.bind is not None
    sessions = async_sessionmaker(
        db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    coordinator = StorageCoordinator(FakeObjectStorage())
    keys = TrustedKeyBuilder(environment="test", bucket=settings.s3_bucket)
    sources = SourceServices(sessions, coordinator, keys, settings)
    assets = AssetServices(
        sessions=sessions,
        coordinator=coordinator,
        keys=keys,
        source_csv_max_bytes=settings.source_csv_max_bytes,
        generated_pdf_max_bytes=settings.generated_pdf_max_bytes,
    )
    review = ImportReviewServices(sessions, settings)
    original = b"date,campaign,currency,clicks\n2026-01-01,A,USD,1\n"
    source, _ = await sources.attach_csv(
        owner.id, report.id, original, "text/csv", "test.csv", "race-source"
    )
    await review.put_configuration(
        owner.id,
        report.id,
        source.id,
        ImportConfigurationRequest(
            expected_revision=0,
            normalization_policy_version="normalize-v1",
            mappings=[
                ColumnMapping(source_column_ordinal=0, canonical_field="date"),
                ColumnMapping(source_column_ordinal=1, canonical_field="campaign_name"),
                ColumnMapping(source_column_ordinal=2, canonical_field="currency"),
                ColumnMapping(source_column_ordinal=3, canonical_field="clicks"),
            ],
        ),
        assets,
    )
    read_original = review._bytes

    async def change_while_reading(*args: object) -> bytes:
        if race == "period":
            await db_session.execute(
                update(Report)
                .where(Report.id == report.id)
                .values(period_revision=Report.period_revision + 1)
            )
            await db_session.flush()
        else:
            await sources.attach_text(owner.id, report.id, "changed", "race-text")
        return await read_original(*args)  # type: ignore[arg-type]

    review._bytes = change_while_reading  # type: ignore[method-assign]
    with pytest.raises((ConcurrencyConflict, ResourceNotFound)):
        await review.validate(
            owner.id, report.id, source.id, ValidateImportRequest(expected_revision=1), assets
        )
    assert await db_session.scalar(select(func.count()).select_from(ImportValidation)) == 0
