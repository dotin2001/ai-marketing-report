"""Public PDF export contracts exclude persistence-only fields."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.version_schemas import (
    CreatePdfExportRequest,
    PdfExportDetail,
    RetryPdfExportRequest,
)


def test_pdf_commands_are_strict() -> None:
    with pytest.raises(ValidationError):
        CreatePdfExportRequest.model_validate({"template_version": "report-v1", "object_key": "x"})
    with pytest.raises(ValidationError):
        RetryPdfExportRequest.model_validate(
            {"input_identity": "0" * 64, "expected_attempt_count": 1, "bucket": "x"}
        )


def test_pdf_detail_rejects_private_storage_reference() -> None:
    now = datetime.now(UTC)
    fields = dict(
        id=uuid4(),
        report_id=uuid4(),
        version_id=uuid4(),
        template_version="report-v1",
        input_identity="0" * 64,
        state="succeeded",
        attempt_count=1,
        created_at=now,
        updated_at=now,
        failure=None,
        attempts=[],
        file=dict(
            filename="report.pdf",
            content_type="application/pdf",
            byte_size=5,
            checksum="1" * 64,
            download_available=True,
            object_key="private",
        ),
    )
    with pytest.raises(ValidationError):
        PdfExportDetail.model_validate(fields)
