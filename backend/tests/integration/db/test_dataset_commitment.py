from __future__ import annotations

from datetime import date
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CanonicalDataset,
    CanonicalRow,
    ConfirmedImport,
    FileAsset,
    ImportConfiguration,
    ImportConfigurationRevision,
    ImportValidation,
    Principal,
    Report,
    ReportSource,
)
from app.db.repositories import ConcurrencyConflict, attach_source, confirm_import_validation
from app.domain.datasets import CanonicalRowInput, commit_confirmed_dataset
from tests.integration.db.conftest import seed_report

pytestmark = pytest.mark.postgres


async def _confirmed(
    session: AsyncSession, subject: str
) -> tuple[Principal, Report, ConfirmedImport]:
    owner, report, _ = await seed_report(session, subject=subject)
    body = b"date,campaign,currency,clicks\n2026-01-01,Launch,USD,5\n"
    asset = FileAsset(
        owner_id=owner.id,
        report_id=report.id,
        purpose="source_csv",
        environment="test",
        bucket="private-test",
        object_key=f"sources/{uuid4()}.csv",
        safe_filename="input.csv",
        content_type="text/csv",
        byte_size=len(body),
        checksum_sha256=sha256(body).digest(),
    )
    source = ReportSource(
        owner_id=owner.id,
        report_id=report.id,
        source_type="csv",
        checksum_sha256=asset.checksum_sha256,
        byte_size=asset.byte_size,
        media_type="text/csv",
        encoding="utf-8",
        original_filename="input.csv",
        display_filename="input.csv",
    )
    await attach_source(session, owner_id=owner.id, report_id=report.id, source=source, asset=asset)
    config = ImportConfiguration(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source.id,
        source_type="csv",
        current_revision=1,
    )
    session.add(config)
    await session.flush()
    session.add(
        ImportConfigurationRevision(
            owner_id=owner.id,
            report_id=report.id,
            configuration_id=config.id,
            revision=1,
            normalization_policy_version="normalize-v1",
        )
    )
    await session.flush()
    validation = ImportValidation(
        owner_id=owner.id,
        report_id=report.id,
        configuration_id=config.id,
        revision=1,
        error_count=0,
        warning_count=0,
        source_checksum=source.checksum_sha256,
        period_start=report.period_start,
        period_end=report.period_end,
        period_revision=report.period_revision,
        total_records=1,
    )
    session.add(validation)
    await session.flush()
    confirmation = await confirm_import_validation(
        session,
        owner_id=owner.id,
        report_id=report.id,
        configuration_id=config.id,
        revision=1,
        validation_id=validation.id,
        confirmed_by=owner.id,
        acknowledged_warning_ids=[],
        canonical_data_identity=sha256(subject.encode()).digest(),
        row_count=1,
        period_start=report.period_start,
        period_end=report.period_end,
    )
    return owner, report, confirmation


@pytest.mark.asyncio
async def test_commit_replay_provenance_and_immutable_history(db_session: AsyncSession) -> None:
    owner, report, confirmation = await _confirmed(db_session, "dataset-commit")
    rows = [CanonicalRowInput(1, date(2026, 1, 1), "Launch", "USD", clicks=5)]
    first = await commit_confirmed_dataset(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        confirmation_id=confirmation.id,
        rows=rows,
    )
    replay = await commit_confirmed_dataset(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        confirmation_id=confirmation.id,
        rows=rows,
    )
    assert first.id == replay.id
    assert first.source_id == report.current_source_id
    assert first.normalization_policy_version == "normalize-v1"
    assert first.period_start == confirmation.period_start
    assert first.canonical_data_identity == confirmation.canonical_data_identity
    stored = (
        await db_session.scalars(select(CanonicalRow).where(CanonicalRow.dataset_id == first.id))
    ).one()
    assert stored.source_record_index == 1 and stored.clicks == 5
    with pytest.raises(ConcurrencyConflict, match="conflicts"):
        await commit_confirmed_dataset(
            db_session,
            owner_id=owner.id,
            report_id=report.id,
            confirmation_id=confirmation.id,
            rows=[CanonicalRowInput(1, date(2026, 1, 1), "Changed", "USD", clicks=5)],
        )
    with pytest.raises(DBAPIError, match="immutable"):
        async with db_session.begin_nested():
            await db_session.delete(first)
            await db_session.flush()
    assert await db_session.get(CanonicalDataset, first.id) is not None


@pytest.mark.asyncio
async def test_commit_rejects_stale_and_malformed_inputs_atomically(
    db_session: AsyncSession,
) -> None:
    owner, report, confirmation = await _confirmed(db_session, "dataset-stale")
    with pytest.raises(ValueError, match="canonical rows"):
        await commit_confirmed_dataset(
            db_session,
            owner_id=owner.id,
            report_id=report.id,
            confirmation_id=confirmation.id,
            rows=[CanonicalRowInput(1, date(2027, 1, 1), "Late", "USD", clicks=1)],
        )
    assert (
        await db_session.scalars(
            select(CanonicalDataset).where(CanonicalDataset.report_id == report.id)
        )
    ).all() == []
    config = (
        await db_session.scalars(
            select(ImportConfiguration).where(
                ImportConfiguration.id == confirmation.configuration_id
            )
        )
    ).one()
    config.current_revision = 2
    await db_session.flush()
    with pytest.raises(ConcurrencyConflict, match="stale"):
        await commit_confirmed_dataset(
            db_session,
            owner_id=owner.id,
            report_id=report.id,
            confirmation_id=confirmation.id,
            rows=[CanonicalRowInput(1, date(2026, 1, 1), "Launch", "USD", clicks=5)],
        )


@pytest.mark.asyncio
async def test_new_confirmation_retains_old_dataset(db_session: AsyncSession) -> None:
    owner, report, original = await _confirmed(db_session, "dataset-history")
    first = await commit_confirmed_dataset(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        confirmation_id=original.id,
        rows=[CanonicalRowInput(1, date(2026, 1, 1), "First", "USD", clicks=5)],
    )
    configuration = (
        await db_session.scalars(
            select(ImportConfiguration).where(ImportConfiguration.id == original.configuration_id)
        )
    ).one()
    configuration.current_revision = 2
    db_session.add(
        ImportConfigurationRevision(
            owner_id=owner.id,
            report_id=report.id,
            configuration_id=configuration.id,
            revision=2,
            normalization_policy_version="normalize-v2",
        )
    )
    await db_session.flush()
    current_source = await db_session.get(ReportSource, configuration.source_id)
    assert current_source is not None
    validation = ImportValidation(
        owner_id=owner.id,
        report_id=report.id,
        configuration_id=configuration.id,
        revision=2,
        error_count=0,
        warning_count=0,
        source_checksum=current_source.checksum_sha256,
        period_start=report.period_start,
        period_end=report.period_end,
        period_revision=report.period_revision,
        total_records=1,
    )
    db_session.add(validation)
    await db_session.flush()
    new_confirmation = await confirm_import_validation(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        configuration_id=configuration.id,
        revision=2,
        validation_id=validation.id,
        confirmed_by=owner.id,
        acknowledged_warning_ids=[],
        canonical_data_identity=sha256(b"new-history").digest(),
        row_count=1,
        period_start=report.period_start,
        period_end=report.period_end,
    )
    second = await commit_confirmed_dataset(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        confirmation_id=new_confirmation.id,
        rows=[CanonicalRowInput(2, date(2026, 2, 1), "Second", "EUR", clicks=8)],
    )
    assert first.id != second.id
    assert report.current_dataset_id == second.id
    assert (
        await db_session.scalars(
            select(CanonicalDataset).where(CanonicalDataset.report_id == report.id)
        )
    ).all() == [first, second]
    assert (
        await db_session.scalars(select(CanonicalRow).where(CanonicalRow.dataset_id == first.id))
    ).one().campaign_name == "First"
