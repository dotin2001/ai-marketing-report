from datetime import date
from decimal import Decimal

import pytest

from app.processing.normalization import NormalizationIssue, normalize

START = date(2026, 1, 1)
END = date(2026, 1, 31)


def value(field: str, original: str, date_format: str | None = None) -> object:
    return normalize(field, original, date_format=date_format, period_start=START, period_end=END)


def test_valid_normalization_keeps_exact_values() -> None:
    assert value("date", "2026-01-31") == END
    assert value("date", "31/01/2026", "%d/%m/%Y") == END
    assert value("campaign_name", "  Café  ") == "Café"
    assert value("currency", " usd ") == "USD"
    assert value("clicks", "00012") == 12
    assert value("spend", "0.30") == Decimal("0.30")


@pytest.mark.parametrize(
    ("field", "original", "code"),
    [
        ("date", "", "missing_value"),
        ("campaign_name", "  ", "blank_campaign_name"),
        ("clicks", "", "missing_value"),
        ("date", "01/02/2026", "ambiguous_date"),
        ("date", "2026-02-30", "invalid_date"),
        ("date", "2026-02-01", "out_of_period"),
        ("currency", "ZZZ", "unsupported_currency"),
        ("clicks", "-1", "negative_measure"),
        ("clicks", "1.5", "invalid_count"),
        ("clicks", "1,000", "invalid_count"),
        ("spend", "-0.01", "negative_measure"),
        ("spend", "$1", "invalid_spend"),
        ("spend", "NaN", "invalid_spend"),
        ("spend", "1%", "invalid_spend"),
    ],
)
def test_invalid_values_report_stable_code(field: str, original: str, code: str) -> None:
    with pytest.raises(NormalizationIssue) as caught:
        value(field, original)
    assert caught.value.code == code
