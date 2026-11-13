from __future__ import annotations

from datetime import date
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ConfirmedImportWarningAcknowledgement,
    FileAsset,
    ImportColumnMapping,
    ImportConfiguration,
    ImportConfigurationRevision,
    ImportValidation,
    ImportValidationIssue,
    ReportSource,
)
from app.db.repositories import (
    ConcurrencyConflict,
    append_import_revision,
    attach_source,
    confirm_import_validation,
    confirm_source_review,
    get_source,
)
from tests.integration.db.conftest import seed_report

pytestmark = pytest.mark.postgres


async def attach_csv_source(
    session: AsyncSession, *, owner_id: UUID, report_id: UUID
) -> ReportSource:
    content = b"date,campaign,currency,clicks\n2026-01-01,Launch,USD,1\n"
    asset = FileAsset(
        owner_id=owner_id,
        report_id=report_id,
        purpose="source_csv",
        environment="test",
        bucket="private-test",
        object_key=f"sources/{uuid4()}.csv",
        safe_filename="report.csv",
        content_type="text/csv",
        byte_size=len(content),
        checksum_sha256=sha256(content).digest(),
    )
    source = ReportSource(
        owner_id=owner_id,
        report_id=report_id,
        source_type="csv",
        checksum_sha256=sha256(content).digest(),
        byte_size=len(content),
        media_type="text/csv",
        encoding="utf-8",
        original_filename="../../report.csv",
        display_filename="report.csv",
    )
    return await attach_source(
        session,
        owner_id=owner_id,
        report_id=report_id,
        source=source,
        asset=asset,
    )


@pytest.mark.asyncio
async def test_text_source_is_exact_and_current_without_storage_io(
    db_session: AsyncSession,
) -> None:
    owner, report, _ = await seed_report(db_session, subject="source-owner")
    content = "Untrusted pasted claim"
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
    await attach_source(db_session, owner_id=owner.id, report_id=report.id, source=source)
    await db_session.flush()
    await db_session.refresh(report)
    assert report.current_source_id == source.id
    assert source.inline_text == content
    assert (
        await get_source(db_session, owner_id=owner.id, report_id=report.id, source_id=source.id)
        is source
    )
    assert (
        await get_source(db_session, owner_id=uuid4(), report_id=report.id, source_id=source.id)
        is None
    )

    confirmation = await confirm_source_review(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        source_id=source.id,
        source_checksum=source.checksum_sha256,
        confirmed_by=owner.id,
    )
    assert confirmation.source_checksum == source.checksum_sha256
    with pytest.raises(ConcurrencyConflict, match="stale"):
        await confirm_source_review(
            db_session,
            owner_id=owner.id,
            report_id=report.id,
            source_id=source.id,
            source_checksum=b"z" * 32,
            confirmed_by=owner.id,
        )


@pytest.mark.asyncio
async def test_ambiguous_source_representation_is_rejected(db_session: AsyncSession) -> None:
    owner, report, _ = await seed_report(db_session, subject="bad-source")
    source = ReportSource(
        owner_id=owner.id,
        report_id=report.id,
        source_type="csv",
        checksum_sha256=b"x" * 32,
        byte_size=1,
        media_type="text/csv",
        encoding="utf-8",
        inline_text="also text",
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(source)
            await db_session.flush()


@pytest.mark.asyncio
async def test_csv_source_rejects_wrong_asset_purpose_and_text_import_configuration(
    db_session: AsyncSession,
) -> None:
    owner, report, _ = await seed_report(db_session, subject="wrong-source-purpose")
    wrong_asset = FileAsset(
        owner_id=owner.id,
        report_id=report.id,
        purpose="generated_pdf",
        environment="test",
        bucket="private-test",
        object_key=f"exports/{uuid4()}.pdf",
        safe_filename="report.pdf",
        content_type="application/pdf",
        byte_size=4,
        checksum_sha256=b"p" * 32,
        version_id=uuid4(),
        export_id=uuid4(),
    )
    db_session.add(wrong_asset)
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                ReportSource(
                    owner_id=owner.id,
                    report_id=report.id,
                    source_type="csv",
                    checksum_sha256=b"c" * 32,
                    byte_size=4,
                    media_type="text/csv",
                    encoding="utf-8",
                    asset_id=wrong_asset.id,
                    asset_purpose="source_csv",
                    original_filename="input.csv",
                    display_filename="input.csv",
                )
            )
            await db_session.flush()

    other_owner, other_report, _ = await seed_report(db_session, subject="foreign-asset-owner")
    foreign_asset = FileAsset(
        owner_id=other_owner.id,
        report_id=other_report.id,
        purpose="source_csv",
        environment="test",
        bucket="private-test",
        object_key=f"sources/{uuid4()}.csv",
        safe_filename="foreign.csv",
        content_type="text/csv",
        byte_size=4,
        checksum_sha256=b"f" * 32,
    )
    db_session.add(foreign_asset)
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                ReportSource(
                    owner_id=owner.id,
                    report_id=report.id,
                    source_type="csv",
                    checksum_sha256=b"f" * 32,
                    byte_size=4,
                    media_type="text/csv",
                    encoding="utf-8",
                    asset_id=foreign_asset.id,
                    asset_purpose="source_csv",
                    original_filename="foreign.csv",
                    display_filename="foreign.csv",
                )
            )
            await db_session.flush()

    text_source = ReportSource(
        owner_id=owner.id,
        report_id=report.id,
        source_type="text",
        checksum_sha256=b"t" * 32,
        byte_size=4,
        media_type="text/plain",
        encoding="utf-8",
        inline_text="text",
    )
    db_session.add(text_source)
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                ImportConfiguration(
                    owner_id=owner.id,
                    report_id=report.id,
                    source_id=text_source.id,
                    source_type="csv",
                    current_revision=1,
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_import_revision_is_append_only_and_compare_and_set(
    db_session: AsyncSession,
) -> None:
    owner, report, _ = await seed_report(db_session, subject="mapping-owner")
    source = await attach_csv_source(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
    )
    config = ImportConfiguration(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source.id,
        source_type="csv",
        current_revision=1,
    )
    db_session.add(config)
    await db_session.flush()
    db_session.add(
        ImportConfigurationRevision(
            owner_id=owner.id,
            report_id=report.id,
            configuration_id=config.id,
            revision=1,
            normalization_policy_version="normalize-v1",
        )
    )
    await db_session.flush()
    with pytest.raises(ValueError, match="required dimensions"):
        await append_import_revision(
            db_session,
            configuration_id=config.id,
            owner_id=owner.id,
            report_id=report.id,
            expected_revision=1,
            normalization_policy_version="normalize-v1",
            mappings=[(0, "date"), (1, "clicks")],
        )
    with pytest.raises(ValueError, match="one measure"):
        await append_import_revision(
            db_session,
            configuration_id=config.id,
            owner_id=owner.id,
            report_id=report.id,
            expected_revision=1,
            normalization_policy_version="normalize-v1",
            mappings=[(0, "date"), (1, "campaign_name"), (2, "currency")],
        )
    mappings = [(0, "date"), (1, "campaign_name"), (2, "currency"), (3, "clicks")]
    assert (
        await append_import_revision(
            db_session,
            configuration_id=config.id,
            owner_id=owner.id,
            report_id=report.id,
            expected_revision=1,
            normalization_policy_version="normalize-v1",
            mappings=mappings,
        )
        == 2
    )
    await db_session.flush()
    with pytest.raises(ConcurrencyConflict):
        await append_import_revision(
            db_session,
            configuration_id=config.id,
            owner_id=owner.id,
            report_id=report.id,
            expected_revision=1,
            normalization_policy_version="normalize-v1",
            mappings=mappings,
        )
    assert (
        len(
            (
                await db_session.scalars(
                    select(ImportColumnMapping).where(
                        ImportColumnMapping.configuration_id == config.id,
                        ImportColumnMapping.revision == 2,
                    )
                )
            ).all()
        )
        == 4
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                ImportColumnMapping(
                    owner_id=owner.id,
                    report_id=report.id,
                    configuration_id=config.id,
                    revision=2,
                    source_column_ordinal=0,
                    canonical_field="leads",
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_import_confirmation_requires_current_error_free_validation_and_all_warnings(
    db_session: AsyncSession,
) -> None:
    owner, report, _ = await seed_report(db_session, subject="confirmation-owner")
    source = await attach_csv_source(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
    )
    config = ImportConfiguration(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source.id,
        source_type="csv",
        current_revision=1,
    )
    db_session.add(config)
    await db_session.flush()
    db_session.add(
        ImportConfigurationRevision(
            owner_id=owner.id,
            report_id=report.id,
            configuration_id=config.id,
            revision=1,
            normalization_policy_version="normalize-v1",
        )
    )
    await db_session.flush()

    error_validation = ImportValidation(
        owner_id=owner.id,
        report_id=report.id,
        configuration_id=config.id,
        revision=1,
        error_count=1,
        warning_count=0,
    )
    db_session.add(error_validation)
    await db_session.flush()
    db_session.add(
        ImportValidationIssue(
            owner_id=owner.id,
            report_id=report.id,
            validation_id=error_validation.id,
            ordinal=1,
            code="missing_value",
            severity="error",
            message="A mapped value is missing",
            source_record_index=1,
        )
    )
    await db_session.flush()
    with pytest.raises(ValueError, match="blocking errors"):
        await confirm_import_validation(
            db_session,
            owner_id=owner.id,
            report_id=report.id,
            configuration_id=config.id,
            revision=1,
            validation_id=error_validation.id,
            confirmed_by=owner.id,
            acknowledged_warning_ids=[],
            canonical_data_identity=b"e" * 32,
            row_count=1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

    warning_validation = ImportValidation(
        owner_id=owner.id,
        report_id=report.id,
        configuration_id=config.id,
        revision=1,
        error_count=0,
        warning_count=1,
    )
    db_session.add(warning_validation)
    await db_session.flush()
    warning = ImportValidationIssue(
        owner_id=owner.id,
        report_id=report.id,
        validation_id=warning_validation.id,
        ordinal=1,
        code="unmapped_column",
        severity="warning",
        message="One source column is unmapped",
        source_column_ordinal=4,
    )
    db_session.add(warning)
    await db_session.flush()
    with pytest.raises(ValueError, match="acknowledgement"):
        await confirm_import_validation(
            db_session,
            owner_id=owner.id,
            report_id=report.id,
            configuration_id=config.id,
            revision=1,
            validation_id=warning_validation.id,
            confirmed_by=owner.id,
            acknowledged_warning_ids=[],
            canonical_data_identity=b"w" * 32,
            row_count=1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
    confirmation = await confirm_import_validation(
        db_session,
        owner_id=owner.id,
        report_id=report.id,
        configuration_id=config.id,
        revision=1,
        validation_id=warning_validation.id,
        confirmed_by=owner.id,
        acknowledged_warning_ids=[warning.id],
        canonical_data_identity=b"w" * 32,
        row_count=1,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )
    assert (
        await db_session.scalar(
            select(ConfirmedImportWarningAcknowledgement).where(
                ConfirmedImportWarningAcknowledgement.confirmation_id == confirmation.id
            )
        )
        is not None
    )

    await append_import_revision(
        db_session,
        configuration_id=config.id,
        owner_id=owner.id,
        report_id=report.id,
        expected_revision=1,
        normalization_policy_version="normalize-v1",
        mappings=[(0, "date"), (1, "campaign_name"), (2, "currency"), (3, "clicks")],
    )
    await db_session.flush()
    with pytest.raises(ConcurrencyConflict, match="stale"):
        await confirm_import_validation(
            db_session,
            owner_id=owner.id,
            report_id=report.id,
            configuration_id=config.id,
            revision=1,
            validation_id=warning_validation.id,
            confirmed_by=owner.id,
            acknowledged_warning_ids=[warning.id],
            canonical_data_identity=b"s" * 32,
            row_count=1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
