from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest

from app.storage.errors import ContentRejected, StorageError, StorageErrorCode
from app.storage.files import prepare_content, verify_download
from app.storage.keys import TrustedKeyBuilder
from app.storage.types import ProviderObject
from tests.unit.storage.helpers import (
    BUILDER,
    EXPORT_ID,
    OWNER_ID,
    REPORT_ID,
    SOURCE_ID,
    VERSION_ID,
    prepared_csv,
)


def test_trusted_keys_are_canonical_purpose_separated_and_environment_scoped() -> None:
    csv = BUILDER.source_csv(owner_id=OWNER_ID, report_id=REPORT_ID, source_id=SOURCE_ID)
    pdf = BUILDER.generated_pdf(
        owner_id=OWNER_ID,
        report_id=REPORT_ID,
        version_id=VERSION_ID,
        export_id=EXPORT_ID,
    )
    assert csv.key == (
        "v1/test/owners/11111111-1111-1111-1111-111111111111/reports/"
        "22222222-2222-2222-2222-222222222222/sources/"
        "33333333-3333-3333-3333-333333333333/original.csv"
    )
    assert "/versions/" in pdf.key and pdf.key.endswith("/report.pdf")
    assert csv.key != pdf.key
    local = TrustedKeyBuilder(environment="local", bucket="private-test")
    assert (
        local.source_csv(owner_id=OWNER_ID, report_id=REPORT_ID, source_id=SOURCE_ID).key != csv.key
    )


@pytest.mark.parametrize(
    "malicious",
    ["../owner.csv", "/absolute.csv", "a/../../b.csv", "header\r\nInjected: yes.csv"],
)
def test_untrusted_filenames_cannot_influence_keys(malicious: str) -> None:
    identity = BUILDER.source_csv(
        owner_id=OWNER_ID,
        report_id=REPORT_ID,
        source_id=SOURCE_ID,
    )
    assert malicious not in identity.key


@pytest.mark.parametrize("bucket", ["../bucket", "UPPERCASE", "a", "bucket/child"])
def test_invalid_configured_bucket_is_rejected(bucket: str) -> None:
    with pytest.raises(ValueError, match="configured storage bucket is invalid"):
        TrustedKeyBuilder(environment="test", bucket=bucket)


@pytest.mark.asyncio
async def test_preparation_preserves_exact_bytes_digest_and_rewinds() -> None:
    content = b"date,campaign\r\n2026-01-01,\xff\r\n"
    prepared = await prepared_csv(content)
    try:
        assert prepared.file.read() == content
        assert prepared.metadata.byte_size == len(content)
        assert prepared.metadata.checksum_sha256 == sha256(content).hexdigest()
    finally:
        prepared.close()
    assert prepared.file.closed


@pytest.mark.asyncio
async def test_preparation_spills_to_disk_and_closes() -> None:
    content = b"x" * 20
    prepared = await prepare_content(
        BytesIO(content),
        identity=BUILDER.source_csv(owner_id=OWNER_ID, report_id=REPORT_ID, source_id=SOURCE_ID),
        owner_id=OWNER_ID,
        report_id=REPORT_ID,
        logical_id=SOURCE_ID,
        safe_filename="source.csv",
        content_type="text/csv",
        max_bytes=20,
        spool_max_bytes=8,
        chunk_size=3,
    )
    assert prepared.rolled_to_disk
    prepared.close()
    assert prepared.file.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("purpose", "content_type"),
    [("csv", "text/csv"), ("pdf", "application/pdf")],
)
async def test_purpose_limits_and_empty_files_are_rejected(purpose: str, content_type: str) -> None:
    identity = (
        BUILDER.source_csv(owner_id=OWNER_ID, report_id=REPORT_ID, source_id=SOURCE_ID)
        if purpose == "csv"
        else BUILDER.generated_pdf(
            owner_id=OWNER_ID,
            report_id=REPORT_ID,
            version_id=VERSION_ID,
            export_id=EXPORT_ID,
        )
    )
    with pytest.raises(ContentRejected, match="byte limit"):
        await prepare_content(
            BytesIO(b"ab"),
            identity=identity,
            owner_id=OWNER_ID,
            report_id=REPORT_ID,
            logical_id=uuid4(),
            safe_filename="file",
            content_type=content_type,
            max_bytes=1,
            chunk_size=1,
        )
    with pytest.raises(ContentRejected, match="must not be empty"):
        await prepare_content(
            BytesIO(b""),
            identity=identity,
            owner_id=OWNER_ID,
            report_id=REPORT_ID,
            logical_id=uuid4(),
            safe_filename="file",
            content_type=content_type,
            max_bytes=1,
        )


@pytest.mark.asyncio
async def test_verified_download_rejects_truncation_and_closes_provider_body() -> None:
    prepared = await prepared_csv()
    body = BytesIO(b"truncated")
    with pytest.raises(StorageError) as error:
        await verify_download(
            ProviderObject(metadata=prepared.metadata, body=body),
            expected=prepared.metadata,
            safe_filename="source.csv",
            max_bytes=prepared.metadata.byte_size,
        )
    assert error.value.code is StorageErrorCode.INTEGRITY_FAILED
    assert body.closed
    prepared.close()
