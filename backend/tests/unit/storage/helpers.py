from __future__ import annotations

from io import BytesIO
from uuid import UUID

from app.storage.files import PreparedContent, prepare_content
from app.storage.keys import TrustedKeyBuilder

OWNER_ID = UUID("11111111-1111-1111-1111-111111111111")
REPORT_ID = UUID("22222222-2222-2222-2222-222222222222")
SOURCE_ID = UUID("33333333-3333-3333-3333-333333333333")
VERSION_ID = UUID("44444444-4444-4444-4444-444444444444")
EXPORT_ID = UUID("55555555-5555-5555-5555-555555555555")
BUILDER = TrustedKeyBuilder(environment="test", bucket="private-test")


async def prepared_csv(content: bytes = b"date,campaign_name\n2026-01-01,A\n") -> PreparedContent:
    return await prepare_content(
        BytesIO(content),
        identity=BUILDER.source_csv(
            owner_id=OWNER_ID,
            report_id=REPORT_ID,
            source_id=SOURCE_ID,
        ),
        owner_id=OWNER_ID,
        report_id=REPORT_ID,
        logical_id=SOURCE_ID,
        safe_filename="source.csv",
        content_type="text/csv",
        max_bytes=1024,
    )


async def prepared_pdf(content: bytes = b"%PDF-1.7\nbody") -> PreparedContent:
    return await prepare_content(
        BytesIO(content),
        identity=BUILDER.generated_pdf(
            owner_id=OWNER_ID,
            report_id=REPORT_ID,
            version_id=VERSION_ID,
            export_id=EXPORT_ID,
        ),
        owner_id=OWNER_ID,
        report_id=REPORT_ID,
        logical_id=EXPORT_ID,
        safe_filename="report-1.pdf",
        content_type="application/pdf",
        max_bytes=1024,
    )
