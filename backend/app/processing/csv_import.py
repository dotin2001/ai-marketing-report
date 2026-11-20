"""Deterministic full-record import validation without source value disclosure."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from typing import cast
from uuid import UUID

from app.processing.normalization import NormalizationIssue, normalize
from app.processing.source_envelope import CsvEnvelope

FIELDS = ("date", "campaign_name", "currency", "impressions", "clicks", "spend", "leads")
REQUIRED = FIELDS[:3]
MEASURES = FIELDS[3:]
MESSAGES = {
    "missing_required_mapping": "A required field needs a source column.",
    "missing_measure_mapping": "Map at least one supported measure.",
    "duplicate_mapping": "A source column or canonical field is mapped more than once.",
    "empty_dataset": "The CSV has no data records.",
    "missing_value": "A mapped field is blank or absent.",
    "invalid_date": "The date is invalid for the selected format.",
    "ambiguous_date": "The date needs an explicit format.",
    "blank_campaign_name": "The campaign name is blank.",
    "unsupported_currency": "The currency code is unsupported.",
    "invalid_count": "The count must be a plain whole number.",
    "invalid_spend": "Spend must be a plain exact decimal number.",
    "negative_measure": "A measure cannot be negative.",
    "out_of_period": "The date is outside the report period.",
    "unmapped_column": "A source column is excluded from calculations.",
    "duplicate_row": "This canonical row duplicates another record; both remain included.",
    "mixed_currency": "Multiple currencies are present; monetary results must be partitioned.",
}


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    message: str
    canonical_field: str | None = None
    source_column_ordinal: int | None = None
    source_record_index: int | None = None
    related_record_index: int | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalRowCandidate:
    source_record_index: int
    row_date: date
    campaign_name: str
    currency: str
    impressions: int | None = None
    clicks: int | None = None
    spend: Decimal | None = None
    leads: int | None = None


@dataclass(frozen=True)
class CsvImportResult:
    issues: tuple[Issue, ...]
    rows: tuple[CanonicalRowCandidate, ...]


def issue(
    code: str,
    *,
    field: str | None = None,
    column: int | None = None,
    record: int | None = None,
    related: int | None = None,
) -> Issue:
    return Issue(
        code,
        "warning" if code in {"unmapped_column", "duplicate_row", "mixed_currency"} else "error",
        MESSAGES[code],
        field,
        column,
        record,
        related,
    )


def process_csv(
    envelope: CsvEnvelope,
    mappings: list[tuple[int, str]],
    *,
    date_format: str | None,
    period_start: date,
    period_end: date,
) -> CsvImportResult:
    issues: list[Issue] = []
    by_field: dict[str, int] = {}
    seen_ordinals: set[int] = set()
    for ordinal, field in mappings:
        if ordinal in seen_ordinals or field in by_field:
            issues.append(issue("duplicate_mapping", field=field, column=ordinal))
        elif field in FIELDS and 0 <= ordinal < len(envelope.columns):
            by_field[field] = ordinal
            seen_ordinals.add(ordinal)
        else:
            issues.append(
                issue(
                    "duplicate_mapping",
                    field=field if field in FIELDS else None,
                    column=ordinal if ordinal >= 0 else None,
                )
            )
    for field in REQUIRED:
        if field not in by_field:
            issues.append(issue("missing_required_mapping", field=field))
    if not any(field in by_field for field in MEASURES):
        issues.append(issue("missing_measure_mapping"))
    if not envelope.records:
        issues.append(issue("empty_dataset"))

    canonical_seen: dict[tuple[object, ...], int] = {}
    candidates: list[CanonicalRowCandidate] = []
    currencies: set[str] = set()
    row_issues: list[Issue] = []
    warnings: list[Issue] = []
    for record in envelope.records:
        normalized: dict[str, date | str | int | Decimal] = {}
        valid = True
        for field, ordinal in sorted(by_field.items(), key=lambda pair: pair[1]):
            raw = record.values[ordinal] if ordinal < len(record.values) else ""
            try:
                normalized[field] = normalize(
                    field,
                    raw,
                    date_format=date_format,
                    period_start=period_start,
                    period_end=period_end,
                )
            except NormalizationIssue as exc:
                row_issues.append(
                    issue(exc.code, field=field, column=ordinal, record=record.record_index)
                )
                valid = False
        if valid and len(normalized) == len(by_field):
            if all(field in normalized for field in REQUIRED) and any(
                field in normalized for field in MEASURES
            ):
                candidates.append(
                    CanonicalRowCandidate(
                        source_record_index=record.record_index,
                        row_date=cast(date, normalized["date"]),
                        campaign_name=cast(str, normalized["campaign_name"]),
                        currency=cast(str, normalized["currency"]),
                        impressions=cast(int | None, normalized.get("impressions")),
                        clicks=cast(int | None, normalized.get("clicks")),
                        spend=cast(Decimal | None, normalized.get("spend")),
                        leads=cast(int | None, normalized.get("leads")),
                    )
                )
            if "currency" in normalized:
                currencies.add(str(normalized["currency"]))
            key = tuple(normalized.get(field) for field in FIELDS)
            previous = canonical_seen.get(key)
            if previous is not None:
                warnings.append(
                    issue("duplicate_row", record=record.record_index, related=previous)
                )
            else:
                canonical_seen[key] = record.record_index
    issues.extend(
        sorted(
            row_issues,
            key=lambda item: (item.source_record_index or 0, item.source_column_ordinal or 0),
        )
    )
    used = set(by_field.values())
    issues.extend(
        issue("unmapped_column", column=column.ordinal)
        for column in envelope.columns
        if column.ordinal not in used
    )
    issues.extend(warnings)
    if len(currencies) > 1:
        issues.append(issue("mixed_currency"))
    return CsvImportResult(tuple(issues), tuple(candidates))


def validate_csv(
    envelope: CsvEnvelope,
    mappings: list[tuple[int, str]],
    *,
    date_format: str | None,
    period_start: date,
    period_end: date,
) -> list[Issue]:
    return list(
        process_csv(
            envelope,
            mappings,
            date_format=date_format,
            period_start=period_start,
            period_end=period_end,
        ).issues
    )


def canonical_data_identity(
    *,
    source_id: UUID,
    source_checksum: bytes,
    configuration_id: UUID,
    revision: int,
    normalization_policy_version: str,
    date_format: str | None,
    period_start: date,
    period_end: date,
    period_revision: int,
    mappings: list[tuple[int, str]],
    rows: tuple[CanonicalRowCandidate, ...],
) -> bytes:
    """SHA-256 of canonical JSON v1 with stable order and decimal text values."""
    payload = {
        "schema": "canonical-data-v1",
        "source_id": str(source_id),
        "source_checksum": source_checksum.hex(),
        "configuration_id": str(configuration_id),
        "revision": revision,
        "normalization_policy_version": normalization_policy_version,
        "date_format": date_format,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "period_revision": period_revision,
        "mappings": [[ordinal, field] for ordinal, field in sorted(mappings)],
        "rows": [
            {
                "source_record_index": row.source_record_index,
                "date": row.row_date.isoformat(),
                "campaign_name": row.campaign_name,
                "currency": row.currency,
                "impressions": row.impressions,
                "clicks": row.clicks,
                "spend": str(row.spend) if row.spend is not None else None,
                "leads": row.leads,
            }
            for row in rows
        ],
    }
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).digest()
