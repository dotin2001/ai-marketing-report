"""Safe public contracts for unconfirmed source intake and preview."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictStr

from app.api.report_schemas import PublicModel, StrictModel


class PasteSourceRequest(StrictModel):
    content: StrictStr = Field(min_length=1)


class SourceDetail(PublicModel):
    id: UUID
    report_id: UUID
    source_type: Literal["csv", "text"]
    byte_size: int
    checksum_sha256: str
    media_type: str
    encoding: str | None
    original_filename_untrusted: str | None
    display_filename: str | None
    created_at: datetime


class SourceEnvelope(StrictModel):
    data: SourceDetail


class PreviewColumn(StrictModel):
    ordinal: int
    original_header: str


class PreviewRow(StrictModel):
    record_index: int
    values: list[str]


class SourcePreview(StrictModel):
    source_type: Literal["csv", "text"]
    confirmed: Literal[False] = False
    validation_status: Literal["unvalidated"] = "unvalidated"
    columns: list[PreviewColumn] | None = None
    rows: list[PreviewRow] | None = None
    total_records: int | None = None
    excerpt: str | None = None
    truncated: bool


class SourcePreviewEnvelope(StrictModel):
    data: SourcePreview
