from datetime import date

from app.processing.csv_import import validate_csv
from app.processing.source_envelope import parse_csv

START = date(2026, 1, 1)
END = date(2026, 1, 31)


def review(content: bytes, mappings: list[tuple[int, str]]) -> list[object]:
    envelope = parse_csv(content, max_bytes=100_000, max_records=1000)
    return validate_csv(envelope, mappings, date_format=None, period_start=START, period_end=END)


def test_full_dataset_validation_and_warning_order() -> None:
    content = (
        b"date,campaign,currency,clicks,extra\n"
        b"2026-01-01,A,USD,2,9\n2026-01-01,A,USD,2,8\n"
        b"2026-01-02,B,EUR,3,7\n2026-01-03,C,USD,wrong,6\n"
    )
    issues = review(content, [(0, "date"), (1, "campaign_name"), (2, "currency"), (3, "clicks")])
    assert [item.code for item in issues] == [
        "invalid_count",
        "unmapped_column",
        "duplicate_row",
        "mixed_currency",
    ]
    assert issues[0].source_record_index == 4
    assert issues[0].source_column_ordinal == 3
    assert issues[0].canonical_field == "clicks"
    assert issues[1].source_column_ordinal == 4
    assert (issues[2].source_record_index, issues[2].related_record_index) == (2, 1)
    assert sum(item.severity == "error" for item in issues) == 1
    assert sum(item.severity == "warning" for item in issues) == 3
    assert all("wrong" not in item.message for item in issues)


def test_incomplete_mapping_and_header_only() -> None:
    issues = review(b"date,date,currency,clicks\n", [(0, "date"), (1, "date")])
    assert [item.code for item in issues[:4]] == [
        "duplicate_mapping",
        "missing_required_mapping",
        "missing_required_mapping",
        "missing_measure_mapping",
    ]
    assert "empty_dataset" in [item.code for item in issues]
    assert issues[0].source_column_ordinal == 1
    assert issues[0].canonical_field == "date"


def test_repeated_headers_and_records_beyond_preview_limit() -> None:
    content = b"date,date,currency,clicks\n2026-01-01,A,USD,1\n2026-01-02,B,USD,broken\n"
    envelope = parse_csv(content, max_bytes=1000, max_records=10)
    assert envelope.columns[0].original_header == envelope.columns[1].original_header
    issues = validate_csv(
        envelope,
        [(0, "date"), (1, "campaign_name"), (2, "currency"), (3, "clicks")],
        date_format=None,
        period_start=START,
        period_end=END,
    )
    assert [(item.code, item.source_record_index) for item in issues] == [("invalid_count", 2)]


def test_missing_mapped_value_is_not_imputed_or_dropped() -> None:
    issues = review(
        b"date,campaign,currency,clicks\n2026-01-01,A,USD,\n",
        [(0, "date"), (1, "campaign_name"), (2, "currency"), (3, "clicks")],
    )
    assert [
        (item.code, item.source_record_index, item.source_column_ordinal) for item in issues
    ] == [("missing_value", 1, 3)]


def test_warning_only_rows_remain_eligible_for_later_confirmation() -> None:
    content = (
        b"date,campaign,currency,clicks,extra\n"
        b"2026-01-01,A,USD,1,first\n"
        b"2026-01-01,A,USD,1,second\n"
        b"2026-01-02,B,EUR,2,third\n"
    )
    issues = review(content, [(0, "date"), (1, "campaign_name"), (2, "currency"), (3, "clicks")])
    assert [item.code for item in issues] == ["unmapped_column", "duplicate_row", "mixed_currency"]
    assert all(item.severity == "warning" for item in issues)
