from __future__ import annotations

from typing import cast

import pytest

from app.processing.source_envelope import SourceEnvelopeError, csv_preview, parse_csv, text_preview


def test_exact_bytes_bom_duplicates_quoted_newline_and_header_only() -> None:
    original = b'\xef\xbb\xbfdate,date\r\n"a\nb",=1\r\n'
    parsed = parse_csv(original, max_bytes=len(original), max_records=1)
    assert [(c.ordinal, c.original_header) for c in parsed.columns] == [(0, "date"), (1, "date")]
    assert parsed.records[0].record_index == 1
    assert parsed.records[0].values == ("a\nb", "=1")
    assert parsed.encoding == "utf-8-sig"
    assert parse_csv(b"a,b\n", max_bytes=4, max_records=1).records == ()


@pytest.mark.parametrize(
    ("data", "max_bytes", "max_records", "media_type", "code"),
    [
        (b"a,b\n1,2", 6, 1, "text/csv", "payload_too_large"),
        (b"a,b\n1,2\n3,4", 20, 1, "text/csv", "payload_too_large"),
        (b'a,b\n"bad', 20, 1, "text/csv", "validation_failed"),
        (b"a,b\n\xff", 20, 1, "text/csv", "unsupported_encoding"),
        (b"a,b\n\x00", 20, 1, "text/csv", "unsupported_media_type"),
        (b"a,b", 20, 1, "image/png", "unsupported_media_type"),
        (b"not a csv", 20, 1, "text/csv", "unsupported_media_type"),
        (b"", 20, 1, "text/csv", "validation_failed"),
    ],
)
def test_rejected_envelopes(
    data: bytes, max_bytes: int, max_records: int, media_type: str, code: str
) -> None:
    with pytest.raises(SourceEnvelopeError) as error:
        parse_csv(data, max_bytes=max_bytes, max_records=max_records, media_type=media_type)
    assert error.value.code == code


def test_previews_are_bounded_and_leave_original_inert() -> None:
    original = b'a,b\n"=SUM(1,2)",123456789\nnext,ok\n'
    parsed = parse_csv(original, max_bytes=100, max_records=2)
    preview = csv_preview(parsed, max_rows=1, max_cell_chars=5, max_response_bytes=1000)
    assert preview["truncated"] is True
    assert preview["rows"] == [{"record_index": 1, "values": ["=SUM(", "12345"]}]
    assert parsed.records[0].values[0] == "=SUM(1,2)"
    assert (
        csv_preview(parsed, max_rows=2, max_cell_chars=20, max_response_bytes=230)["truncated"]
        is True
    )
    text = "表" * 100 + "=1+1"
    excerpt = text_preview(text, max_chars=50, max_response_bytes=120)
    assert excerpt["truncated"] is True
    assert len(cast(str, excerpt["excerpt"]).encode()) < 120
    assert text.endswith("=1+1")
