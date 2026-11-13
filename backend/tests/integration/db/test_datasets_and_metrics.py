from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import Numeric, Table, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Base
from app.db.models import (
    CanonicalDataset,
    CanonicalRow,
    DatasetCurrency,
    FileAsset,
    ImportConfiguration,
    ImportConfigurationRevision,
    ImportValidation,
    MetricResult,
    MetricResultCurrency,
    MetricResultInput,
    MetricResultSet,
    Report,
    ReportSource,
)
from app.db.repositories import (
    attach_dataset_and_metrics,
    attach_source,
    confirm_import_validation,
)
from tests.integration.db.conftest import seed_report

pytestmark = pytest.mark.postgres


async def seed_dataset_metric_aggregate(
    session: AsyncSession,
    *,
    subject: str,
    row_date: date = date(2026, 1, 1),
) -> tuple[Report, CanonicalDataset, CanonicalRow, MetricResultSet, MetricResult]:
    owner, report, _ = await seed_report(session, subject=subject)
    content = b"date,campaign,currency,impressions,clicks\n2026-01-01,Launch,USD,100,0\n"
    asset = FileAsset(
        owner_id=owner.id,
        report_id=report.id,
        purpose="source_csv",
        environment="test",
        bucket="private-test",
        object_key=f"sources/{uuid4()}.csv",
        safe_filename="input.csv",
        content_type="text/csv",
        byte_size=len(content),
        checksum_sha256=sha256(content).digest(),
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
    await attach_source(
        session,
        owner_id=owner.id,
        report_id=report.id,
        source=source,
        asset=asset,
    )
    configuration = ImportConfiguration(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source.id,
        source_type="csv",
        current_revision=1,
    )
    session.add(configuration)
    await session.flush()
    session.add(
        ImportConfigurationRevision(
            owner_id=owner.id,
            report_id=report.id,
            configuration_id=configuration.id,
            revision=1,
            normalization_policy_version="normalize-v1",
        )
    )
    await session.flush()
    validation = ImportValidation(
        owner_id=owner.id,
        report_id=report.id,
        configuration_id=configuration.id,
        revision=1,
        error_count=0,
        warning_count=0,
    )
    session.add(validation)
    await session.flush()
    canonical_identity = sha256(f"canonical-{subject}".encode()).digest()
    confirmation = await confirm_import_validation(
        session,
        owner_id=owner.id,
        report_id=report.id,
        configuration_id=configuration.id,
        revision=1,
        validation_id=validation.id,
        confirmed_by=owner.id,
        acknowledged_warning_ids=[],
        canonical_data_identity=canonical_identity,
        row_count=1,
        period_start=report.period_start,
        period_end=report.period_end,
    )
    dataset = CanonicalDataset(
        owner_id=owner.id,
        report_id=report.id,
        source_id=source.id,
        confirmation_id=confirmation.id,
        canonical_data_identity=canonical_identity,
        normalization_policy_version="normalize-v1",
        period_start=report.period_start,
        period_end=report.period_end,
        row_count=1,
    )
    placeholder = uuid4()
    currency = DatasetCurrency(
        dataset_id=placeholder,
        currency="USD",
        owner_id=owner.id,
        report_id=report.id,
    )
    row = CanonicalRow(
        owner_id=owner.id,
        report_id=report.id,
        dataset_id=placeholder,
        source_record_index=1,
        row_date=row_date,
        campaign_name="Launch",
        currency="USD",
        impressions=100,
        clicks=0,
    )
    metric_set = MetricResultSet(
        owner_id=owner.id,
        report_id=report.id,
        dataset_id=placeholder,
        identity=sha256(f"metrics-{subject}".encode()).digest(),
        calculation_version="kpi-v1",
        calculated_at=datetime.now(UTC),
    )
    metric_id = uuid4()
    metric = MetricResult(
        id=metric_id,
        owner_id=owner.id,
        report_id=report.id,
        result_set_id=placeholder,
        metric_name="ctr",
        availability="available",
        scope="report",
        period_start=report.period_start,
        period_end=report.period_end,
        value=Decimal("0"),
        unit="percent",
    )
    metric_input = MetricResultInput(
        owner_id=owner.id,
        report_id=report.id,
        metric_result_id=metric_id,
        ordinal=1,
        input_name="clicks",
        exact_total=Decimal("0"),
    )
    metric_currency = MetricResultCurrency(
        metric_result_id=metric_id,
        currency="USD",
        owner_id=owner.id,
        report_id=report.id,
    )
    await attach_dataset_and_metrics(
        session,
        report=report,
        dataset=dataset,
        dataset_currencies=[currency],
        rows=[row],
        metric_set=metric_set,
        metric_results=[metric],
        metric_inputs=[metric_input],
        metric_currencies=[metric_currency],
    )
    return report, dataset, row, metric_set, metric


@pytest.mark.asyncio
async def test_canonical_row_structural_checks_reject_invalid_values(
    db_session: AsyncSession,
) -> None:
    report, dataset, _stored_row, _metric_set, _metric = await seed_dataset_metric_aggregate(
        db_session, subject="row-owner"
    )
    row = CanonicalRow(
        owner_id=report.owner_id,
        report_id=report.id,
        dataset_id=dataset.id,
        source_record_index=2,
        row_date=date(2026, 1, 1),
        campaign_name="Campaign",
        currency="USD",
        impressions=-1,
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(row)
            await db_session.flush()

    duplicate = CanonicalRow(
        owner_id=report.owner_id,
        report_id=report.id,
        dataset_id=dataset.id,
        source_record_index=1,
        row_date=date(2026, 1, 2),
        campaign_name="Duplicate",
        currency="USD",
        clicks=1,
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(duplicate)
            await db_session.flush()


@pytest.mark.asyncio
async def test_dataset_repository_rejects_out_of_period_rows(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="outside the dataset period"):
        await seed_dataset_metric_aggregate(
            db_session,
            subject="out-of-period-row",
            row_date=date(2025, 12, 31),
        )


@pytest.mark.asyncio
async def test_zero_metric_is_available_and_mixed_or_nonfinite_variants_are_rejected(
    db_session: AsyncSession,
) -> None:
    report, _dataset, _row, metric_set, metric = await seed_dataset_metric_aggregate(
        db_session, subject="metric-variants"
    )
    assert metric.value == Decimal("0") and metric.unavailable_reason is None
    invalid = MetricResult(
        owner_id=report.owner_id,
        report_id=report.id,
        result_set_id=metric_set.id,
        metric_name="cpc",
        availability="available",
        scope="currency",
        period_start=report.period_start,
        period_end=report.period_end,
        currency="USD",
        value=Decimal("NaN"),
        unit="USD/click",
        unavailable_reason="zero_denominator",
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(invalid)
            await db_session.flush()


@pytest.mark.asyncio
async def test_dataset_and_metric_tables_reject_update_and_delete(db_session: AsyncSession) -> None:
    _report, _dataset, row, _metric_set, _metric = await seed_dataset_metric_aggregate(
        db_session, subject="immutable-metrics"
    )
    with pytest.raises(DBAPIError, match="immutable table canonical_rows rejects UPDATE"):
        async with db_session.begin_nested():
            row.campaign_name = "Mutated through ORM"
            await db_session.flush()
    await db_session.refresh(row)
    assert row.campaign_name == "Launch"
    table_names = (
        "canonical_datasets",
        "dataset_currencies",
        "canonical_rows",
        "metric_result_sets",
        "metric_results",
        "metric_result_inputs",
        "metric_result_currencies",
    )
    for table_name in table_names:
        table = Base.metadata.tables[table_name]
        for statement, operation in (
            (table.update().values(owner_id=table.c.owner_id), "UPDATE"),
            (table.delete(), "DELETE"),
        ):
            with pytest.raises(
                DBAPIError,
                match=rf"immutable table {table_name} rejects {operation}",
            ):
                async with db_session.begin_nested():
                    await db_session.execute(statement)


@pytest.mark.asyncio
async def test_new_source_clears_current_results_without_deleting_history(
    db_session: AsyncSession,
) -> None:
    report, dataset, _row, metric_set, _metric = await seed_dataset_metric_aggregate(
        db_session, subject="metric-invalidation"
    )
    assert report.current_dataset_id == dataset.id
    assert report.current_metric_result_set_id == metric_set.id
    content = "Replacement untrusted source"
    replacement = ReportSource(
        owner_id=report.owner_id,
        report_id=report.id,
        source_type="text",
        checksum_sha256=sha256(content.encode()).digest(),
        byte_size=len(content.encode()),
        media_type="text/plain",
        encoding="utf-8",
        inline_text=content,
    )
    await attach_source(
        db_session,
        owner_id=report.owner_id,
        report_id=report.id,
        source=replacement,
    )
    await db_session.flush()
    pointers = (
        await db_session.execute(
            select(
                Report.current_source_id,
                Report.current_dataset_id,
                Report.current_metric_result_set_id,
                Report.current_analysis_result_id,
            ).where(Report.id == report.id)
        )
    ).one()
    assert tuple(pointers) == (replacement.id, None, None, None)
    assert await db_session.scalar(
        select(CanonicalDataset).where(CanonicalDataset.id == dataset.id)
    )


def test_metric_variant_metadata_admits_zero_and_rejects_mixed_fields() -> None:
    table = cast(Table, MetricResult.__table__)
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if hasattr(constraint, "sqltext")
    }
    availability = checks["ck_metric_results_availability_variant"]
    assert "value IS NOT NULL" in availability
    assert "value = 0" not in availability
    assert "unavailable_reason IS NULL" in availability


def test_exact_numeric_types_are_not_binary_float() -> None:
    row_table = cast(Table, CanonicalRow.__table__)
    metric_table = cast(Table, MetricResult.__table__)
    assert cast(Numeric[Decimal], row_table.c.spend.type).asdecimal is True
    assert cast(Numeric[Decimal], metric_table.c.value.type).asdecimal is True
    assert Decimal("0.10") + Decimal("0.20") == Decimal("0.30")
    assert datetime.now(UTC).tzinfo is not None
