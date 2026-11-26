from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.version_schemas import CreateVersionRequest, RestoreVersionRequest, VersionDetail
from app.db.snapshots import ReportVersionSnapshotV2


def test_version_commands_reject_extra_and_invalid_fields() -> None:
    for model, payload in (
        (CreateVersionRequest, {"expected_draft_revision": 1, "template_version": "custom"}),
        (CreateVersionRequest, {"expected_draft_revision": 0}),
        (RestoreVersionRequest, {"expected_draft_id": str(uuid4()), "expected_draft_revision": 0}),
        (
            RestoreVersionRequest,
            {
                "expected_draft_id": str(uuid4()),
                "expected_draft_revision": 1,
                "owner_id": str(uuid4()),
            },
        ),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_version_detail_rejects_nested_private_references_and_serializes_utc() -> None:
    report_id, draft_id, source_id = uuid4(), uuid4(), uuid4()
    snapshot: dict[str, Any] = {
        "schema_version": 2,
        "report_id": str(report_id),
        "report_name": "Report",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "objectives": ["Explain performance"],
        "source": {
            "source_id": str(source_id),
            "source_type": "text",
            "checksum_sha256": "a" * 64,
            "byte_size": 12,
            "media_type": "text/plain",
        },
        "metrics": [],
        "narrative": [],
        "limitations": [],
        "claims": [],
        "template_version": "report-v1",
    }
    fields = {
        "id": uuid4(),
        "report_id": report_id,
        "version_number": 1,
        "source_draft_id": draft_id,
        "source_draft_revision": 1,
        "template_version": "report-v1",
        "snapshot_schema_version": 2,
        "snapshot_identity": "b" * 64,
        "dataset_id": None,
        "metric_result_set_id": None,
        "analysis_result_id": None,
        "latest_pdf_export": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    result = VersionDetail.model_validate({**fields, "snapshot": snapshot})
    assert isinstance(result.snapshot, ReportVersionSnapshotV2)
    assert result.model_dump(mode="json")["created_at"].endswith("Z")
    with pytest.raises(ValidationError):
        VersionDetail.model_validate({**fields, "snapshot": {**snapshot, "object_key": "private"}})
    with pytest.raises(ValidationError):
        VersionDetail.model_validate(
            {
                **fields,
                "snapshot": {**snapshot, "source": {**snapshot["source"], "inline_text": "secret"}},
            }
        )
