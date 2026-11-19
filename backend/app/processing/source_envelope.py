"""Strict CSV intake envelope and bounded, unconfirmed source previews."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass


class SourceEnvelopeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SourceColumn:
    ordinal: int
    original_header: str


@dataclass(frozen=True)
class SourceRecord:
    record_index: int
    values: tuple[str, ...]


@dataclass(frozen=True)
class CsvEnvelope:
    columns: tuple[SourceColumn, ...]
    records: tuple[SourceRecord, ...]
    byte_size: int
    encoding: str


def parse_csv(
    data: bytes, *, max_bytes: int, max_records: int, media_type: str = "text/csv"
) -> CsvEnvelope:
    if media_type.split(";", 1)[0].strip().lower() not in {"text/csv", "application/csv"}:
        raise SourceEnvelopeError("unsupported_media_type")
    if len(data) > max_bytes:
        raise SourceEnvelopeError("payload_too_large")
    if not data:
        raise SourceEnvelopeError("validation_failed")
    if b"\x00" in data:
        raise SourceEnvelopeError("unsupported_media_type")
    try:
        decoded = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceEnvelopeError("unsupported_encoding") from exc
    if any(ord(char) < 32 and char not in "\r\n\t" for char in decoded):
        raise SourceEnvelopeError("unsupported_media_type")
    try:
        reader = csv.reader(
            io.StringIO(decoded, newline=""), delimiter=",", quotechar='"', strict=True
        )
        header = next(reader)
        if not header or not any(cell for cell in header):
            raise SourceEnvelopeError("validation_failed")
        # A one-column file with no delimiter has no detectable CSV structure.
        if len(header) == 1 and "," not in decoded:
            raise SourceEnvelopeError("unsupported_media_type")
        records: list[SourceRecord] = []
        for index, row in enumerate(reader, 1):
            if index > max_records:
                raise SourceEnvelopeError("payload_too_large")
            records.append(SourceRecord(index, tuple(row)))
    except (csv.Error, StopIteration) as exc:
        raise SourceEnvelopeError("validation_failed") from exc
    return CsvEnvelope(
        tuple(SourceColumn(i, name) for i, name in enumerate(header)),
        tuple(records),
        len(data),
        "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8",
    )


def _fit(value: str, max_chars: int) -> str:
    return value[:max_chars]


def csv_preview(
    envelope: CsvEnvelope, *, max_rows: int, max_cell_chars: int, max_response_bytes: int
) -> dict[str, object]:
    columns = [
        {"ordinal": c.ordinal, "original_header": _fit(c.original_header, max_cell_chars)}
        for c in envelope.columns
    ]
    result: dict[str, object] = {
        "source_type": "csv",
        "confirmed": False,
        "columns": columns,
        "rows": [],
        "truncated": False,
        "total_records": len(envelope.records),
    }
    if len(json.dumps(result, ensure_ascii=False).encode()) > max_response_bytes:
        raise SourceEnvelopeError("payload_too_large")
    rows: list[dict[str, object]] = []
    for record in envelope.records[:max_rows]:
        candidate = {
            "record_index": record.record_index,
            "values": [_fit(v, max_cell_chars) for v in record.values],
        }
        rows.append(candidate)
        result["rows"] = rows
        if len(json.dumps(result, ensure_ascii=False).encode()) > max_response_bytes:
            rows.pop()
            break
    result["truncated"] = (
        len(rows) < len(envelope.records)
        or any(len(v) > max_cell_chars for r in envelope.records[: len(rows)] for v in r.values)
        or any(len(c.original_header) > max_cell_chars for c in envelope.columns)
    )
    return result


def text_preview(content: str, *, max_chars: int, max_response_bytes: int) -> dict[str, object]:
    excerpt = content[:max_chars]
    result: dict[str, object] = {
        "source_type": "text",
        "confirmed": False,
        "validation_status": "unvalidated",
        "excerpt": excerpt,
        "truncated": len(content) > len(excerpt),
    }
    while excerpt and len(json.dumps(result, ensure_ascii=False).encode()) > max_response_bytes:
        excerpt = excerpt[:-1]
        result["excerpt"] = excerpt
        result["truncated"] = True
    if len(json.dumps(result, ensure_ascii=False).encode()) > max_response_bytes:
        raise SourceEnvelopeError("payload_too_large")
    return result
