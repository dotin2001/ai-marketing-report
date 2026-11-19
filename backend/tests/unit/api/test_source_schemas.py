from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.source_schemas import PasteSourceRequest, SourceDetail, SourceEnvelope, SourcePreview


def test_pasted_unicode_is_unchanged_and_extra_fields_rejected() -> None:
    assert PasteSourceRequest(content=" 表\n=1 ").content == " 表\n=1 "
    with pytest.raises(ValidationError):
        PasteSourceRequest.model_validate({"content": "ok", "object_key": "secret"})


def test_source_detail_labels_untrusted_filename_and_redacts_asset() -> None:
    detail = SourceDetail(
        id=uuid4(),
        report_id=uuid4(),
        source_type="csv",
        byte_size=8,
        checksum_sha256="0" * 64,
        media_type="text/csv",
        encoding="utf-8",
        original_filename_untrusted="../evil.csv",
        display_filename="evil.csv",
        created_at=datetime.now(UTC),
    )
    dumped = SourceEnvelope(data=detail).model_dump(mode="json")
    assert dumped["data"]["original_filename_untrusted"] == "../evil.csv"
    assert dumped["data"]["display_filename"] == "evil.csv"
    assert "object_key" not in str(dumped)
    with pytest.raises(ValidationError):
        SourceDetail.model_validate({**detail.model_dump(), "asset_id": str(uuid4())})
    assert SourcePreview(source_type="text", excerpt="=1", truncated=False).confirmed is False
