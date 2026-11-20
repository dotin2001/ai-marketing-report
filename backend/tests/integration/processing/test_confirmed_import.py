"""Atomic owner-confirmed CSV normalization with PostgreSQL and verified storage."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command as alembic_command
from app.api.source_schemas import (
    ColumnMapping,
    ConfirmImportRequest,
    ImportConfigurationRequest,
    ImportValidationDetail,
    ValidateImportRequest,
)
from app.core.config import Settings
from app.db.models import (
    CanonicalDataset,
    CanonicalRow,
    ConfirmedImport,
    DatasetCurrency,
    ImportColumnMapping,
    Report,
)
from app.db.repositories import IdempotencyConflict
from app.db.testing import validate_test_database
from app.domain.assets import AssetServices, ResourceNotFound
from app.domain.import_confirmation import (
    BlockedImportValidation,
    ImportConfirmationServices,
    StaleImportInput,
    WarningAcknowledgementRequired,
)
from app.domain.import_review import ImportReviewServices
from app.domain.sources import SourceServices
from app.storage.coordinator import StorageCoordinator
from app.storage.fake import FakeObjectStorage
from app.storage.keys import TrustedKeyBuilder
from tests.integration.db.conftest import seed_report

pytestmark = pytest.mark.postgres


@dataclass
class PreparedImport:
    owner_id: UUID
    report_id: UUID
    source_id: UUID
    validation: ImportValidationDetail
    review: ImportReviewServices
    confirm: ImportConfirmationServices
    sources: SourceServices
    assets: AssetServices


async def prepare_import(
    db_session: AsyncSession,
    settings: Settings,
    content: bytes,
    *,
    mappings: list[tuple[int, str]] | None = None,
    date_format: str | None = None,
    commit_seed: bool = False,
) -> PreparedImport:
    owner, report, _ = await seed_report(db_session, subject=str(uuid4()))
    if commit_seed:
        await db_session.commit()
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
    confirm = ImportConfirmationServices(sessions, settings)
    source, _ = await sources.attach_csv(
        owner.id, report.id, content, "text/csv", "../secret.csv", "prepare-csv"
    )
    chosen = mappings or [
        (0, "date"),
        (1, "campaign_name"),
        (2, "currency"),
        (3, "clicks"),
        (4, "spend"),
    ]
    await review.put_configuration(
        owner.id,
        report.id,
        source.id,
        ImportConfigurationRequest(
            expected_revision=0,
            normalization_policy_version="normalize-v1",
            date_format=date_format,
            mappings=[
                ColumnMapping.model_validate(
                    {"source_column_ordinal": ordinal, "canonical_field": field}
                )
                for ordinal, field in chosen
            ],
        ),
        assets,
    )
    validation = await review.validate(
        owner.id, report.id, source.id, ValidateImportRequest(expected_revision=1), assets
    )
    return PreparedImport(
        owner.id, report.id, source.id, validation, review, confirm, sources, assets
    )


def command(
    prepared: PreparedImport, *, warnings: list[UUID] | None = None, revision: int = 1
) -> ConfirmImportRequest:
    return ConfirmImportRequest(
        validation_id=prepared.validation.id,
        expected_revision=revision,
        acknowledged_warning_ids=warnings
        if warnings is not None
        else [issue.id for issue in prepared.validation.issues if issue.severity == "warning"],
    )


@pytest.mark.asyncio
async def test_confirmation_commits_exact_rows_currency_and_replay(
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    content = (
        b"date,campaign,currency,clicks,spend,extra\n"
        b"2026-01-01, A ,usd,2,0.10,999\n"
        b"2026-01-01, A ,usd,2,0.10,123\n"
        b"2026-01-02,B,eur,3,0.20,1000\n"
    )
    prepared = await prepare_import(db_session, settings, content)
    assert [issue.code for issue in prepared.validation.issues] == [
        "unmapped_column",
        "duplicate_row",
        "mixed_currency",
    ]
    detail, replayed = await prepared.confirm.confirm(
        prepared.owner_id,
        prepared.report_id,
        prepared.source_id,
        command(prepared),
        "confirm-1",
        prepared.assets,
    )
    assert replayed is False
    assert detail.row_count == 3
    assert detail.currencies == ["EUR", "USD"]
    assert detail.source_checksum_sha256 == prepared.validation.source_checksum_sha256
    assert [item.canonical_field for item in detail.mappings] == [
        "date",
        "campaign_name",
        "currency",
        "clicks",
        "spend",
    ]
    replay, replayed = await prepared.confirm.confirm(
        prepared.owner_id,
        prepared.report_id,
        prepared.source_id,
        command(prepared),
        "confirm-1",
        prepared.assets,
    )
    assert replayed and replay.id == detail.id and replay.dataset_id == detail.dataset_id
    rows = list(
        (
            await db_session.scalars(
                select(CanonicalRow)
                .where(CanonicalRow.dataset_id == detail.dataset_id)
                .order_by(CanonicalRow.source_record_index)
            )
        ).all()
    )
    assert [row.source_record_index for row in rows] == [1, 2, 3]
    assert [row.campaign_name for row in rows] == ["A", "A", "B"]
    assert [row.currency for row in rows] == ["USD", "USD", "EUR"]
    assert [row.spend for row in rows] == [Decimal("0.10"), Decimal("0.10"), Decimal("0.20")]
    assert [row.clicks for row in rows] == [2, 2, 3]
    currencies = set(
        await db_session.scalars(
            select(DatasetCurrency.currency).where(DatasetCurrency.dataset_id == detail.dataset_id)
        )
    )
    assert currencies == {"USD", "EUR"}
    assert await db_session.scalar(select(func.count()).select_from(ConfirmedImport)) == 1
    assert await db_session.scalar(select(func.count()).select_from(CanonicalDataset)) == 1
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ImportColumnMapping)
            .where(ImportColumnMapping.configuration_id == detail.configuration_id)
        )
        == 5
    )
    with pytest.raises(IdempotencyConflict):
        await prepared.confirm.confirm(
            prepared.owner_id,
            prepared.report_id,
            prepared.source_id,
            command(prepared, warnings=[]),
            "confirm-1",
            prepared.assets,
        )
    await prepared.sources.attach_text(
        prepared.owner_id, prepared.report_id, "new source", "later-source"
    )
    historical, replayed = await prepared.confirm.confirm(
        prepared.owner_id,
        prepared.report_id,
        prepared.source_id,
        command(prepared),
        "confirm-1",
        prepared.assets,
    )
    assert replayed and historical.dataset_id == detail.dataset_id
    with pytest.raises(StaleImportInput):
        await prepared.confirm.confirm(
            prepared.owner_id,
            prepared.report_id,
            prepared.source_id,
            command(prepared),
            "new-key",
            prepared.assets,
        )


@pytest.mark.asyncio
async def test_errors_warnings_and_stale_period_do_not_commit(
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    invalid = await prepare_import(
        db_session, settings, b"date,campaign,currency,clicks,spend\n01/02/2026,A,USD,1,0.10\n"
    )
    assert invalid.validation.confirmation_blocked
    assert invalid.validation.issues[0].code == "ambiguous_date"
    with pytest.raises(BlockedImportValidation):
        await invalid.confirm.confirm(
            invalid.owner_id,
            invalid.report_id,
            invalid.source_id,
            command(invalid),
            "blocked",
            invalid.assets,
        )
    assert await db_session.scalar(select(func.count()).select_from(CanonicalDataset)) == 0
    warning = await prepare_import(
        db_session,
        settings,
        b"date,campaign,currency,clicks,spend,extra\n2026-01-01,A,USD,1,0.10,x\n",
    )
    with pytest.raises(WarningAcknowledgementRequired):
        await warning.confirm.confirm(
            warning.owner_id,
            warning.report_id,
            warning.source_id,
            command(warning, warnings=[]),
            "missing-warning",
            warning.assets,
        )
    warning_ids = [item.id for item in warning.validation.issues if item.severity == "warning"]
    with pytest.raises(WarningAcknowledgementRequired):
        await warning.confirm.confirm(
            warning.owner_id,
            warning.report_id,
            warning.source_id,
            command(warning, warnings=warning_ids * 2),
            "duplicate-warning",
            warning.assets,
        )
    await db_session.execute(
        update(Report)
        .where(Report.id == warning.report_id)
        .values(period_revision=Report.period_revision + 1)
    )
    await db_session.flush()
    with pytest.raises(StaleImportInput):
        await warning.confirm.confirm(
            warning.owner_id,
            warning.report_id,
            warning.source_id,
            command(warning),
            "stale-period",
            warning.assets,
        )
    assert await db_session.scalar(select(func.count()).select_from(CanonicalDataset)) == 0


@pytest.mark.asyncio
async def test_explicit_date_revision_resolves_ambiguity_and_old_review_stales(
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    prepared = await prepare_import(
        db_session, settings, b"date,campaign,currency,clicks,spend\n02/01/2026, A ,usd,1,0.30\n"
    )
    assert prepared.validation.issues[0].code == "ambiguous_date"
    await prepared.review.put_configuration(
        prepared.owner_id,
        prepared.report_id,
        prepared.source_id,
        ImportConfigurationRequest(
            expected_revision=1,
            normalization_policy_version="normalize-v1",
            date_format="%d/%m/%Y",
            mappings=[
                ColumnMapping.model_validate(
                    {"source_column_ordinal": ordinal, "canonical_field": field}
                )
                for ordinal, field in enumerate(
                    ("date", "campaign_name", "currency", "clicks", "spend")
                )
            ],
        ),
        prepared.assets,
    )
    with pytest.raises(StaleImportInput):
        await prepared.confirm.confirm(
            prepared.owner_id,
            prepared.report_id,
            prepared.source_id,
            command(prepared),
            "old-review",
            prepared.assets,
        )
    current = await prepared.review.validate(
        prepared.owner_id,
        prepared.report_id,
        prepared.source_id,
        ValidateImportRequest(expected_revision=2),
        prepared.assets,
    )
    assert current.error_count == 0
    detail, _ = await prepared.confirm.confirm(
        prepared.owner_id,
        prepared.report_id,
        prepared.source_id,
        ConfirmImportRequest(
            validation_id=current.id, expected_revision=2, acknowledged_warning_ids=[]
        ),
        "resolved",
        prepared.assets,
    )
    row = await db_session.scalar(
        select(CanonicalRow).where(CanonicalRow.dataset_id == detail.dataset_id)
    )
    assert row is not None
    assert row.row_date.isoformat() == "2026-01-02"
    assert row.campaign_name == "A" and row.currency == "USD"
    assert row.spend == Decimal("0.30")


@pytest.mark.asyncio
async def test_atomic_rollback_and_owner_scope(
    db_session: AsyncSession,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = await prepare_import(
        db_session, settings, b"date,campaign,currency,clicks,spend\n2026-01-01,A,USD,1,0.10\n"
    )
    with pytest.raises(ResourceNotFound):
        await prepared.confirm.confirm(
            uuid4(),
            prepared.report_id,
            prepared.source_id,
            command(prepared),
            "foreign",
            prepared.assets,
        )
    import app.domain.import_confirmation as module

    async def fail_commit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated database failure")

    original = module.commit_confirmed_dataset
    monkeypatch.setattr(module, "commit_confirmed_dataset", fail_commit)
    with pytest.raises(RuntimeError, match="simulated"):
        await prepared.confirm.confirm(
            prepared.owner_id,
            prepared.report_id,
            prepared.source_id,
            command(prepared),
            "rollback",
            prepared.assets,
        )
    monkeypatch.setattr(module, "commit_confirmed_dataset", original)
    assert await db_session.scalar(select(func.count()).select_from(ConfirmedImport)) == 0
    assert await db_session.scalar(select(func.count()).select_from(CanonicalDataset)) == 0
    detail, _ = await prepared.confirm.confirm(
        prepared.owner_id,
        prepared.report_id,
        prepared.source_id,
        command(prepared),
        "rollback",
        prepared.assets,
    )
    assert detail.row_count == 1


@pytest.mark.asyncio
async def test_concurrent_same_key_creates_one_confirmation(
    settings: Settings,
) -> None:
    target = validate_test_database(
        app_env=os.environ.get("APP_ENV"),
        test_database_url=os.environ.get("TEST_DATABASE_URL"),
        database_url=os.environ.get("DATABASE_URL"),
    )
    schema = "gh11_concurrent_" + uuid4().hex
    admin = create_async_engine(target.url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        previous_options = os.environ.get("PGOPTIONS")
        previous_migration_url = os.environ.get("MIGRATION_DATABASE_URL")
        os.environ["PGOPTIONS"] = f"-csearch_path={schema}"
        os.environ["MIGRATION_DATABASE_URL"] = target.url
        try:
            await asyncio.to_thread(
                alembic_command.upgrade, Config(Path(__file__).parents[3] / "alembic.ini"), "head"
            )
        finally:
            if previous_options is None:
                os.environ.pop("PGOPTIONS", None)
            else:
                os.environ["PGOPTIONS"] = previous_options
            if previous_migration_url is None:
                os.environ.pop("MIGRATION_DATABASE_URL", None)
            else:
                os.environ["MIGRATION_DATABASE_URL"] = previous_migration_url
        engine = create_async_engine(
            target.url, connect_args={"options": f"-csearch_path={schema}"}
        )
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                prepared = await prepare_import(
                    session,
                    settings,
                    b"date,campaign,currency,clicks,spend\n2026-01-01,A,USD,1,0.10\n",
                    commit_seed=True,
                )
            calls = await asyncio.gather(
                *(
                    prepared.confirm.confirm(
                        prepared.owner_id,
                        prepared.report_id,
                        prepared.source_id,
                        command(prepared),
                        "concurrent-confirm",
                        prepared.assets,
                    )
                    for _ in range(2)
                )
            )
            assert calls[0][0].id == calls[1][0].id
            assert sorted(replayed for _, replayed in calls) == [False, True]
            async with AsyncSession(engine) as session:
                assert await session.scalar(select(func.count()).select_from(ConfirmedImport)) == 1
                assert await session.scalar(select(func.count()).select_from(CanonicalDataset)) == 1
        finally:
            await engine.dispose()
    finally:
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
