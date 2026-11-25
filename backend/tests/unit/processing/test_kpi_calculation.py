from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.domain.datasets import CanonicalRowInput
from app.processing.kpi_calculation import (
    ComparableResult,
    calculate_kpis,
    campaign_identity,
    compare_periods,
    result_set_identity,
)

START = date(2026, 1, 1)
END = date(2026, 1, 7)


def row(
    index: int, *, campaign: str = "A", currency: str = "USD", **measures: object
) -> CanonicalRowInput:
    return CanonicalRowInput(index, START, campaign, currency, **measures)


def metric(
    rows: list[CanonicalRowInput], name: str, *, scope: str = "report", currency: str | None = None
):
    return next(
        item
        for item in calculate_kpis(rows, period_start=START, period_end=END)
        if item.metric_name == name and item.scope == scope and item.currency == currency
    )


def test_aggregate_ctr_and_duplicates_are_included() -> None:
    rows = [row(1, impressions=10, clicks=1), row(2, impressions=100, clicks=1)]
    result = metric(rows, "ctr")
    assert result.value is not None and result.value.startswith("1.818181818181")
    assert result.inputs == (("clicks", "2"), ("impressions", "110"))
    duplicate = metric([rows[0], replace(rows[0], source_record_index=2)], "ctr")
    assert duplicate.inputs == (("clicks", "2"), ("impressions", "20"))
    assert duplicate.value == "10"


def test_exact_spend_currency_and_campaign_groups() -> None:
    rows = [
        row(1, spend=Decimal("0.10"), clicks=1),
        row(2, spend=Decimal("0.20"), clicks=2),
        row(3, campaign="B", currency="EUR", spend=Decimal("20"), clicks=4),
    ]
    usd = metric(rows, "cpc", currency="USD")
    eur = metric(rows, "cpc", currency="EUR")
    assert usd.value == "0.10" and usd.inputs == (("spend", "0.30"), ("clicks", "3"))
    assert eur.value == "5" and eur.unit == "EUR/click"
    assert usd.represented_currencies == ("EUR", "USD")
    assert metric(rows, "cpc", scope="campaign", currency="EUR").campaign_name == "B"
    assert campaign_identity("A") != campaign_identity("B")
    cross = metric(rows, "cpc")
    assert cross.unavailable_reason == "incompatible_currency"
    assert cross.value is None and cross.unit is None
    assert "spend" not in dict(cross.inputs)


def test_missing_zero_and_nonterminating_cases() -> None:
    missing = metric([row(1, clicks=10, spend=Decimal("25"))], "ctr")
    assert (
        missing.unavailable_reason == "missing_input" and missing.supporting_field == "impressions"
    )
    assert missing.value is None and missing.unit is None
    zero = metric([row(1, impressions=0, clicks=0, spend=Decimal("25"))], "ctr")
    assert zero.unavailable_reason == "zero_denominator"
    true_zero = metric([row(1, impressions=100, clicks=0)], "ctr")
    assert true_zero.value == "0" and true_zero.unavailable_reason is None
    cpm = metric([row(1, spend=Decimal("1"), impressions=3)], "cpm", currency="USD")
    assert cpm.value is not None and cpm.value.startswith("333.333333333333")
    invalid = metric([row(1, spend=Decimal("NaN"), clicks=1)], "cpc", currency="USD")
    assert invalid.unavailable_reason == "invalid_input" and invalid.value is None


def test_identity_and_period_comparison() -> None:
    canonical = bytes.fromhex("ab" * 32)
    assert result_set_identity(canonical) == result_set_identity(canonical)
    assert result_set_identity(canonical) != result_set_identity(canonical, "kpi-v2")
    assert result_set_identity(canonical) != result_set_identity(bytes.fromhex("cd" * 32))
    first = ComparableResult(
        "first",
        "ctr",
        "10",
        "percent",
        START,
        END,
        "inclusive",
        "kpi-v1",
        "clicks/impressions*100",
        1,
        "normalize-v1",
        "report",
        "report",
        None,
    )
    second = replace(
        first,
        identity="second",
        period_start=date(2026, 1, 8),
        period_end=date(2026, 1, 14),
        value="20",
    )
    assert compare_periods(first, second)["value"] == "10"
    incompatible = compare_periods(
        first,
        replace(second, period_end=date(2026, 1, 15), normalization_policy_version="normalize-v2"),
    )
    assert incompatible["unavailable_reason"] == "incomparable_period"
    assert incompatible["details"] == ["duration", "normalization_policy_version"]
    assert "value" not in incompatible


def test_all_missing_and_zero_denominator_variants() -> None:
    absent_clicks = [row(1, impressions=1000, spend=Decimal("25"))]
    assert metric(absent_clicks, "ctr").supporting_field == "clicks"
    assert metric(absent_clicks, "cpc", currency="USD").unavailable_reason == "missing_input"
    absent_spend = [row(1, impressions=1000, clicks=10, leads=2)]
    for name in ("cpc", "cpm", "cpl"):
        result = metric(absent_spend, name, currency="USD")
        assert result.unavailable_reason == "missing_input"
        assert result.supporting_field == "spend"
    assert metric([row(1, spend=Decimal("25"))], "cpl", currency="USD").supporting_field == "leads"
    zero_impressions = [row(1, impressions=0, clicks=0, spend=Decimal("25"))]
    assert metric(zero_impressions, "cpm", currency="USD").unavailable_reason == "zero_denominator"
    zero_clicks = [row(1, impressions=100, clicks=0, spend=Decimal("25"))]
    assert metric(zero_clicks, "cpc", currency="USD").unavailable_reason == "zero_denominator"
    assert metric(zero_clicks, "ctr").value == "0"
    zero_leads = [row(1, leads=0, spend=Decimal("25"))]
    assert metric(zero_leads, "cpl", currency="USD").unavailable_reason == "zero_denominator"


def test_currency_partitions_and_deterministic_rerun() -> None:
    rows = [
        row(1, currency="USD", spend=Decimal("30"), clicks=3),
        row(2, currency="EUR", spend=Decimal("20"), clicks=4),
    ]
    first = calculate_kpis(rows, period_start=START, period_end=END)
    second = calculate_kpis(rows, period_start=START, period_end=END)
    assert first == second
    assert metric(rows, "cpc", currency="USD").value == "10"
    assert metric(rows, "cpc", currency="EUR").value == "5"
    assert metric(rows, "cpc").unavailable_reason == "incompatible_currency"
    assert "spend" not in dict(metric(rows, "cpc").inputs)


def test_large_exact_aggregate_total_is_not_rounded() -> None:
    spend = Decimal("1234567890123456789012345678901234567890.01")
    rows = [row(1, spend=spend, clicks=1), row(2, spend=Decimal("0.02"), clicks=1)]
    result = metric(rows, "cpc", currency="USD")
    assert result.inputs[0] == ("spend", "1234567890123456789012345678901234567890.03")


def test_comparison_rejects_each_incompatible_contract_attribute() -> None:
    baseline = ComparableResult(
        "a",
        "ctr",
        "10",
        "percent",
        START,
        END,
        "inclusive",
        "kpi-v1",
        "clicks/impressions*100",
        1,
        "normalize-v1",
        "report",
        "report",
        None,
    )
    other = replace(
        baseline,
        identity="b",
        period_start=date(2026, 1, 8),
        period_end=date(2026, 1, 14),
        value="20",
    )
    changes = {
        "boundary_policy": "exclusive",
        "definition": "other",
        "calculation_version": "kpi-v2",
        "mapping_revision": 2,
        "normalization_policy_version": "normalize-v2",
        "scope": "campaign",
        "group_identity": campaign_identity("A"),
        "currency": "USD",
    }
    for attribute, changed in changes.items():
        result = compare_periods(baseline, replace(other, **{attribute: changed}))
        assert result["availability"] == "unavailable"
        assert attribute in result["details"]
        assert "value" not in result
