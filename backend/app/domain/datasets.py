"""Commit a confirmed CSV as an append-only canonical dataset."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CanonicalDataset,
    CanonicalRow,
    ConfirmedImport,
    DatasetCurrency,
    ImportConfiguration,
    ImportConfigurationRevision,
    ImportValidation,
    ImportValidationIssue,
    Report,
    ReportSource,
)
from app.db.repositories import ConcurrencyConflict


@dataclass(frozen=True, slots=True)
class CanonicalRowInput:
    source_record_index: int
    row_date: date
    campaign_name: str
    currency: str
    impressions: int | None = None
    clicks: int | None = None
    spend: Decimal | None = None
    leads: int | None = None


def _stored_row(row: CanonicalRow) -> CanonicalRowInput:
    return CanonicalRowInput(
        source_record_index=row.source_record_index,
        row_date=row.row_date,
        campaign_name=row.campaign_name,
        currency=row.currency,
        impressions=row.impressions,
        clicks=row.clicks,
        spend=row.spend,
        leads=row.leads,
    )


async def commit_confirmed_dataset(
    session: AsyncSession,
    *,
    owner_id: UUID,
    report_id: UUID,
    confirmation_id: UUID,
    rows: Sequence[CanonicalRowInput],
) -> CanonicalDataset:
    """Commit within the caller's transaction; a failed check leaves no new rows."""
    report = await session.scalar(
        select(Report)
        .where(
            Report.id == report_id,
            Report.owner_id == owner_id,
        )
        .with_for_update()
    )
    confirmation = await session.scalar(
        select(ConfirmedImport).where(
            ConfirmedImport.id == confirmation_id,
            ConfirmedImport.report_id == report_id,
            ConfirmedImport.owner_id == owner_id,
        )
    )
    if report is None or confirmation is None or report.current_source_id is None:
        raise ConcurrencyConflict("current confirmed CSV input is unavailable")
    configuration = await session.scalar(
        select(ImportConfiguration).where(
            ImportConfiguration.id == confirmation.configuration_id,
            ImportConfiguration.report_id == report_id,
            ImportConfiguration.owner_id == owner_id,
            ImportConfiguration.source_id == report.current_source_id,
            ImportConfiguration.source_type == "csv",
            ImportConfiguration.current_revision == confirmation.revision,
        )
    )
    revision = await session.scalar(
        select(ImportConfigurationRevision).where(
            ImportConfigurationRevision.configuration_id == confirmation.configuration_id,
            ImportConfigurationRevision.revision == confirmation.revision,
            ImportConfigurationRevision.report_id == report_id,
            ImportConfigurationRevision.owner_id == owner_id,
        )
    )
    validation = await session.scalar(
        select(ImportValidation).where(
            ImportValidation.id == confirmation.validation_id,
            ImportValidation.configuration_id == confirmation.configuration_id,
            ImportValidation.revision == confirmation.revision,
            ImportValidation.report_id == report_id,
            ImportValidation.owner_id == owner_id,
        )
    )
    source = await session.scalar(
        select(ReportSource).where(
            ReportSource.id == report.current_source_id,
            ReportSource.report_id == report_id,
            ReportSource.owner_id == owner_id,
            ReportSource.source_type == "csv",
        )
    )
    if configuration is None or revision is None or validation is None or source is None:
        raise ConcurrencyConflict("confirmed CSV provenance is stale")
    if validation.error_count != 0:
        raise ValueError("confirmed CSV validation has errors")
    errors = (
        await session.scalars(
            select(ImportValidationIssue).where(
                ImportValidationIssue.validation_id == validation.id,
                ImportValidationIssue.report_id == report_id,
                ImportValidationIssue.owner_id == owner_id,
                ImportValidationIssue.severity == "error",
            )
        )
    ).first()
    if errors is not None:
        raise ValueError("confirmed CSV validation contains an error issue")
    if (
        report.period_start != confirmation.period_start
        or report.period_end != confirmation.period_end
    ):
        raise ConcurrencyConflict("report period changed after import confirmation")
    incoming = tuple(sorted(rows, key=lambda row: row.source_record_index))
    indexes = [row.source_record_index for row in incoming]
    currencies = {row.currency for row in incoming}
    if (
        len(incoming) != confirmation.row_count
        or not incoming
        or len(indexes) != len(set(indexes))
        or any(index <= 0 for index in indexes)
        or any(
            row.row_date < confirmation.period_start or row.row_date > confirmation.period_end
            for row in incoming
        )
        or any(
            not row.campaign_name.strip()
            or not row.currency.isupper()
            or len(row.currency) != 3
            or all(value is None for value in (row.impressions, row.clicks, row.spend, row.leads))
            for row in incoming
        )
    ):
        raise ValueError("canonical rows do not match confirmed input")
    existing = await session.scalar(
        select(CanonicalDataset).where(
            CanonicalDataset.canonical_data_identity == confirmation.canonical_data_identity,
        )
    )
    if existing is not None:
        actual = tuple(
            _stored_row(row)
            for row in (
                await session.scalars(
                    select(CanonicalRow)
                    .where(CanonicalRow.dataset_id == existing.id)
                    .order_by(CanonicalRow.source_record_index)
                )
            ).all()
        )
        stored_currencies = set(
            await session.scalars(
                select(DatasetCurrency.currency).where(
                    DatasetCurrency.dataset_id == existing.id,
                )
            )
        )
        if (
            existing.owner_id != owner_id
            or existing.report_id != report_id
            or existing.source_id != source.id
            or existing.confirmation_id != confirmation_id
            or existing.normalization_policy_version != revision.normalization_policy_version
            or existing.period_start != confirmation.period_start
            or existing.period_end != confirmation.period_end
            or existing.row_count != confirmation.row_count
            or stored_currencies != currencies
            or actual != incoming
        ):
            raise ConcurrencyConflict("canonical identity conflicts with existing dataset")
        report.current_dataset_id = existing.id
        return existing
    dataset = CanonicalDataset(
        owner_id=owner_id,
        report_id=report_id,
        source_id=source.id,
        confirmation_id=confirmation_id,
        canonical_data_identity=confirmation.canonical_data_identity,
        normalization_policy_version=revision.normalization_policy_version,
        period_start=confirmation.period_start,
        period_end=confirmation.period_end,
        row_count=len(incoming),
    )
    session.add(dataset)
    await session.flush()
    session.add_all(
        DatasetCurrency(
            dataset_id=dataset.id,
            currency=currency,
            owner_id=owner_id,
            report_id=report_id,
        )
        for currency in sorted(currencies)
    )
    await session.flush()
    session.add_all(
        CanonicalRow(
            dataset_id=dataset.id,
            owner_id=owner_id,
            report_id=report_id,
            source_record_index=row.source_record_index,
            row_date=row.row_date,
            campaign_name=row.campaign_name,
            currency=row.currency,
            impressions=row.impressions,
            clicks=row.clicks,
            spend=row.spend,
            leads=row.leads,
        )
        for row in incoming
    )
    await session.flush()
    report.current_dataset_id = dataset.id
    report.current_metric_result_set_id = None
    report.current_analysis_result_id = None
    return dataset
