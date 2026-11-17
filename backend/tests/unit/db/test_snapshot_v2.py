from __future__ import annotations

from datetime import date
from typing import cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.snapshots import ReportVersionSnapshotV2, parse_report_version_snapshot
from tests.unit.db.test_snapshots import valid_snapshot


def valid_structured_v2() -> dict[str, object]:
    data = valid_snapshot()
    identity = "b" * 64
    metric_id = uuid4()
    data.update(
        {
            "schema_version": 2,
            "dataset_id": uuid4(),
            "metric_result_set_id": uuid4(),
            "analysis_result_id": None,
            "confirmed_import": {
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
                "canonical_data_identity": identity,
                "row_count": 1,
                "currencies": ["USD"],
            },
            "canonical_data_identity": identity,
            "metrics": [
                {
                    "metric_result_id": metric_id,
                    "name": "ctr",
                    "availability": "available",
                    "value": "0",
                    "unit": "percent",
                    "exact_inputs": {"clicks": "0", "impressions": "100"},
                    "scope": "report",
                    "period_start": date(2026, 1, 1),
                    "period_end": date(2026, 3, 31),
                    "calculation_version": "kpi-v1",
                }
            ],
            "charts": [
                {
                    "chart_type": "bar",
                    "title": "Click rate",
                    "scope": "report",
                    "metric_result_ids": [metric_id],
                }
            ],
        }
    )
    return data


def test_schema_two_accepts_explicit_bindings_and_keeps_schema_one_readable() -> None:
    old = parse_report_version_snapshot(valid_snapshot())
    assert old.schema_version == 1
    new = parse_report_version_snapshot(valid_structured_v2())
    assert isinstance(new, ReportVersionSnapshotV2)
    assert new.dataset_id is not None
    assert new.charts[0].metric_result_ids == (new.metrics[0].metric_result_id,)


@pytest.mark.parametrize("bad_key", ["value", "numeric_override", "object_key", "signed_url"])
def test_schema_two_rejects_chart_overrides_and_private_keys(bad_key: str) -> None:
    data = valid_structured_v2()
    chart = cast(list[dict[str, object]], data["charts"])[0]
    chart[bad_key] = 5
    with pytest.raises(ValidationError):
        ReportVersionSnapshotV2.model_validate(data)


def test_schema_two_rejects_missing_chart_metric() -> None:
    data = valid_structured_v2()
    data["charts"] = [
        {"chart_type": "line", "title": "Wrong", "scope": "report", "metric_result_ids": [uuid4()]}
    ]
    with pytest.raises(ValidationError, match="absent from the snapshot"):
        ReportVersionSnapshotV2.model_validate(data)


def test_schema_two_rejects_incomplete_structured_and_text_only_bindings() -> None:
    data = valid_structured_v2()
    data["dataset_id"] = None
    with pytest.raises(ValidationError, match="dataset binding"):
        ReportVersionSnapshotV2.model_validate(data)

    text = valid_snapshot()
    text["schema_version"] = 2
    text["source"] = {**text["source"], "source_type": "text"}  # type: ignore[dict-item]
    text["dataset_id"] = None
    text["metric_result_set_id"] = None
    text["analysis_result_id"] = None
    text["charts"] = []
    assert ReportVersionSnapshotV2.model_validate(text).dataset_id is None
    text["dataset_id"] = uuid4()
    with pytest.raises(ValidationError, match="text-only"):
        ReportVersionSnapshotV2.model_validate(text)
