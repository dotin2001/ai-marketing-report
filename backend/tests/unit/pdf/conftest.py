from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.db.repositories import report_snapshot_identity
from app.db.snapshots import ReportVersionSnapshot, ReportVersionSnapshotV2
from app.pdf.version import SavedVersion


@pytest.fixture
def version_factory():  # type: ignore[no-untyped-def]
    def make(schema: int = 2, text_only: bool = False) -> SavedVersion:
        report_id, source_id, dataset_id, metric_set_id, analysis_id = (uuid4() for _ in range(5))
        ctr_id, cpm_id, cpc_id = (uuid4() for _ in range(3))
        source: dict[str, Any] = {
            "source_id": source_id,
            "source_type": "text" if text_only else "csv",
            "checksum_sha256": "a" * 64,
            "byte_size": 100,
            "media_type": "text/plain" if text_only else "text/csv",
        }
        confirmed = (
            None
            if text_only
            else {
                "confirmation_id": uuid4(),
                "configuration_id": uuid4(),
                "configuration_revision": 1,
                "normalization_policy_version": "v1",
                "mappings": [
                    {"source_column_ordinal": 0, "canonical_field": "date"},
                    {"source_column_ordinal": 1, "canonical_field": "campaign_name"},
                    {"source_column_ordinal": 2, "canonical_field": "currency"},
                    {"source_column_ordinal": 3, "canonical_field": "clicks"},
                ],
                "validation_id": uuid4(),
                "canonical_data_identity": "b" * 64,
                "row_count": 3,
                "currencies": ["USD"],
            }
        )

        def metric(
            metric_id: Any, name: str, value: str | None, unit: str | None
        ) -> dict[str, Any]:
            return {
                "metric_result_id": metric_id,
                "name": name,
                "availability": "available" if value is not None else "unavailable",
                "value": value,
                "unit": unit,
                "unavailable_reason": None if value is not None else "zero_denominator",
                "exact_inputs": {"clicks": "12", "impressions": "96"},
                "scope": "report",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "currency": None,
                "calculation_version": "v1",
            }

        data: dict[str, Any] = {
            "schema_version": schema,
            "report_id": report_id,
            "report_name": "Báo cáo hiệu quả <script>alert('x')</script>",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "objectives": ["Đánh giá hiệu quả và doanh thu"],
            "source": source,
            "confirmed_import": confirmed,
            "canonical_data_identity": None if text_only else "b" * 64,
            "metrics": []
            if text_only
            else [
                metric(ctr_id, "ctr", "1.2500", "%"),
                metric(cpm_id, "cpm", "2.5000", "%"),
                metric(cpc_id, "cpc", None, None),
            ],
            "analysis": None
            if text_only
            else {
                "result_id": analysis_id,
                "model_identifier": "test-model",
                "prompt_version": "v1",
                "request_provenance": "validated-snapshot",
                "semantic_input_identity": "c" * 64,
                "numeric_source_identity": "d" * 64,
                "items": [
                    {
                        "section": "recommendations",
                        "ordinal": 1,
                        "classification": "hypothesis",
                        "content": "Thử chiến dịch mới.",
                    },
                ],
            },
            "narrative": [
                {
                    "item_id": uuid4(),
                    "section": "findings",
                    "ordinal": 2,
                    "classification": "observation",
                    "content": "Độ tăng trưởng ổn định.",
                },
                {
                    "item_id": uuid4(),
                    "section": "findings",
                    "ordinal": 1,
                    "classification": "hypothesis",
                    "content": "Có thể cải thiện.",
                },
            ],
            "limitations": ["Dữ liệu có giới hạn."],
            "claims": [
                {"claim_id": uuid4(), "ordinal": 1, "content": "Khách hàng nói tăng trưởng cao."}
            ],
            "template_version": "report-v1",
        }
        if schema == 2:
            data.update(
                {
                    "dataset_id": None if text_only else dataset_id,
                    "metric_result_set_id": None if text_only else metric_set_id,
                    "analysis_result_id": None if text_only else analysis_id,
                    "charts": []
                    if text_only
                    else [
                        {
                            "chart_type": "bar",
                            "title": "So sánh tỷ lệ",
                            "scope": "report",
                            "metric_result_ids": [ctr_id, cpm_id],
                        },
                        {
                            "chart_type": "line",
                            "title": "Xu hướng",
                            "scope": "report",
                            "metric_result_ids": [ctr_id, cpm_id],
                        },
                        {
                            "chart_type": "table",
                            "title": "Giá trị chưa có",
                            "scope": "report",
                            "metric_result_ids": [ctr_id, cpc_id],
                        },
                    ],
                }
            )
        snapshot = (
            ReportVersionSnapshotV2.model_validate(data)
            if schema == 2
            else ReportVersionSnapshot.model_validate(data)
        )
        return SavedVersion(
            version_id=uuid4(),
            report_id=report_id,
            version_number=3,
            created_at=datetime(2026, 2, 1, tzinfo=UTC),
            snapshot_identity=report_snapshot_identity(snapshot),
            snapshot_schema_version=schema,
            template_version="report-v1",
            snapshot_json=snapshot.model_dump_json().encode(),
        )

    return make
