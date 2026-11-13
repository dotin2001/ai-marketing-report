from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.snapshots import ReportVersionSnapshot


def valid_snapshot() -> dict[str, object]:
    report_id = uuid4()
    return {
        "schema_version": 1,
        "report_id": report_id,
        "report_name": "Quarterly performance",
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 3, 31),
        "objectives": ["Explain acquisition performance"],
        "source": {
            "source_id": uuid4(),
            "source_type": "csv",
            "checksum_sha256": "a" * 64,
            "byte_size": 100,
            "media_type": "text/csv",
            "display_filename": "report.csv",
        },
        "confirmed_import": None,
        "canonical_data_identity": None,
        "metrics": [],
        "analysis": None,
        "narrative": [],
        "limitations": [],
        "claims": [],
        "template_version": "report-v1",
    }


def test_snapshot_accepts_only_versioned_public_safe_shape() -> None:
    snapshot = ReportVersionSnapshot.model_validate(valid_snapshot())
    assert snapshot.schema_version == 1


def test_snapshot_accepts_complete_reproducibility_shape() -> None:
    data = valid_snapshot()
    confirmation_id = uuid4()
    metric_id = uuid4()
    claim_id = uuid4()
    canonical_identity = "b" * 64
    data.update(
        {
            "confirmed_import": {
                "confirmation_id": confirmation_id,
                "configuration_id": uuid4(),
                "configuration_revision": 2,
                "normalization_policy_version": "normalize-v1",
                "date_format": "%Y-%m-%d",
                "mappings": [
                    {"source_column_ordinal": 1, "canonical_field": "date"},
                    {"source_column_ordinal": 2, "canonical_field": "campaign_name"},
                    {"source_column_ordinal": 3, "canonical_field": "currency"},
                    {"source_column_ordinal": 4, "canonical_field": "spend"},
                ],
                "validation_id": uuid4(),
                "warning_codes": ["trimmed_header"],
                "canonical_data_identity": canonical_identity,
                "row_count": 1,
                "currencies": ["USD"],
            },
            "canonical_data_identity": canonical_identity,
            "metrics": [
                {
                    "metric_result_id": metric_id,
                    "name": "cpc",
                    "availability": "available",
                    "value": "2.50",
                    "unit": "USD/click",
                    "exact_inputs": {"spend": "5.00", "clicks": "2"},
                    "represented_currencies": ["USD"],
                    "scope": "report",
                    "period_start": date(2026, 1, 1),
                    "period_end": date(2026, 3, 31),
                    "currency": "USD",
                    "calculation_version": "kpi-v1",
                }
            ],
            "analysis": {
                "result_id": uuid4(),
                "model_identifier": "test-model",
                "prompt_version": "analysis-v1",
                "request_provenance": "bounded computed metrics",
                "semantic_input_identity": "c" * 64,
                "numeric_source_identity": "d" * 64,
                "items": [
                    {
                        "section": "findings",
                        "ordinal": 1,
                        "classification": "observation",
                        "content": "CPC was 2.50 USD.",
                        "metric_result_ids": [metric_id],
                        "claim_ids": [],
                    }
                ],
            },
            "narrative": [
                {
                    "item_id": uuid4(),
                    "section": "findings",
                    "ordinal": 1,
                    "classification": "observation",
                    "content": "CPC was 2.50 USD.",
                }
            ],
            "limitations": ["Only one campaign was supplied."],
            "claims": [
                {
                    "claim_id": claim_id,
                    "ordinal": 1,
                    "classification": "user_claim",
                    "content": "The launch focused on awareness.",
                }
            ],
        }
    )
    parsed = ReportVersionSnapshot.model_validate(data)
    assert parsed.confirmed_import is not None
    assert parsed.metrics[0].exact_inputs == {"spend": "5.00", "clicks": "2"}
    assert parsed.analysis is not None and parsed.analysis.items[0].claim_ids == ()


@pytest.mark.parametrize("forbidden", ["object_key", "signed_url", "inline_text", "raw_prompt"])
def test_snapshot_rejects_unrestricted_or_secret_bearing_fields(forbidden: str) -> None:
    data = valid_snapshot()
    data[forbidden] = "must-not-be-retained"
    with pytest.raises(ValidationError):
        ReportVersionSnapshot.model_validate(data)


def test_snapshot_rejects_forbidden_nested_dictionary_key() -> None:
    data = valid_snapshot()
    data["source"] = {**data["source"], "signed_url": "https://invalid.example"}  # type: ignore[dict-item]
    with pytest.raises(ValidationError, match="forbidden private field"):
        ReportVersionSnapshot.model_validate(data)


@pytest.mark.parametrize(
    ("availability", "value", "unit", "reason"),
    [
        ("available", None, "percent", None),
        ("available", "1", None, None),
        ("available", "1", "percent", "missing_input"),
        ("unavailable", "1", None, "missing_input"),
        ("unavailable", None, None, None),
    ],
)
def test_snapshot_rejects_conflicting_metric_availability(
    availability: str, value: str | None, unit: str | None, reason: str | None
) -> None:
    data = valid_snapshot()
    canonical_identity = "e" * 64
    data["confirmed_import"] = {
        "confirmation_id": uuid4(),
        "configuration_id": uuid4(),
        "configuration_revision": 1,
        "normalization_policy_version": "normalize-v1",
        "mappings": [
            {"source_column_ordinal": 1, "canonical_field": "date"},
            {"source_column_ordinal": 2, "canonical_field": "campaign_name"},
            {"source_column_ordinal": 3, "canonical_field": "currency"},
            {"source_column_ordinal": 4, "canonical_field": "clicks"},
        ],
        "validation_id": uuid4(),
        "canonical_data_identity": canonical_identity,
        "row_count": 1,
        "currencies": ["USD"],
    }
    data["canonical_data_identity"] = canonical_identity
    data["metrics"] = [
        {
            "metric_result_id": uuid4(),
            "name": "ctr",
            "availability": availability,
            "value": value,
            "unit": unit,
            "unavailable_reason": reason,
            "exact_inputs": {"clicks": "1"},
            "scope": "report",
            "period_start": date(2026, 1, 1),
            "period_end": date(2026, 3, 31),
            "calculation_version": "kpi-v1",
        }
    ]
    with pytest.raises(ValidationError, match="metric fields conflict"):
        ReportVersionSnapshot.model_validate(data)
