"""Pure, versioned KPI calculation from confirmed canonical rows."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from hashlib import sha256
from typing import Protocol

CALCULATION_VERSION = "kpi-v1"
GROUP_CONTRACT = "report-and-exact-campaign-v1"
METRIC_ORDER = ("ctr", "cpc", "cpm", "cpl")


def metric_order_key(
    scope: str,
    campaign_name: str | None,
    metric_name: str,
    currency: str | None,
) -> tuple[int, str, int, str]:
    """Stable public ordering: report, then exact campaign; KPI and currency within each."""
    return (
        0 if scope == "report" else 1 if scope == "campaign" else 2,
        campaign_name or "",
        METRIC_ORDER.index(metric_name),
        currency or "",
    )


class CanonicalInput(Protocol):
    source_record_index: int
    row_date: date
    campaign_name: str
    currency: str
    impressions: int | None
    clicks: int | None
    spend: Decimal | None
    leads: int | None


@dataclass(frozen=True, slots=True)
class CalculatedMetric:
    metric_name: str
    scope: str
    group_identity: str
    campaign_name: str | None
    currency: str | None
    represented_currencies: tuple[str, ...]
    period_start: date
    period_end: date
    inputs: tuple[tuple[str, str], ...]
    value: str | None
    unit: str | None
    unavailable_reason: str | None
    supporting_field: str | None = None


def result_set_identity(canonical_identity: bytes, version: str = CALCULATION_VERSION) -> bytes:
    payload = json.dumps([canonical_identity.hex(), version, GROUP_CONTRACT], separators=(",", ":"))
    return sha256(payload.encode()).digest()


def campaign_identity(name: str) -> str:
    return sha256(name.encode("utf-8")).hexdigest()


def _decimal_string(value: Decimal) -> str:
    return format(value, "f")


def _exact_sum(values: list[int | Decimal]) -> Decimal:
    decimals = [Decimal(value) for value in values]
    integer_digits = max(max(value.adjusted() + 1, 1) for value in decimals)
    fractional_digits = max(max(-int(value.as_tuple().exponent), 0) for value in decimals)
    with localcontext() as context:
        context.prec = max(38, integer_digits + fractional_digits + len(str(len(values))) + 2)
        return sum(decimals, Decimal(0))


def _one(
    rows: Sequence[CanonicalInput],
    metric: str,
    scope: str,
    group: str,
    campaign: str | None,
    currency: str | None,
    start: date,
    end: date,
) -> CalculatedMetric:
    represented = tuple(sorted({row.currency for row in rows}))
    selected = [row for row in rows if currency is None or row.currency == currency]
    numerator, denominator, multiplier, unit = {
        "ctr": ("clicks", "impressions", 100, "percent"),
        "cpc": ("spend", "clicks", 1, f"{currency}/click"),
        "cpm": ("spend", "impressions", 1000, f"{currency}/1000_impressions"),
        "cpl": ("spend", "leads", 1, f"{currency}/lead"),
    }[metric]
    names = (numerator, denominator)
    totals: list[tuple[str, str]] = []
    missing: str | None = None
    invalid: str | None = None
    cross_currency = metric != "ctr" and currency is None and len(represented) > 1
    with localcontext() as context:
        context.prec = 38
        for name in names:
            if cross_currency and name == "spend":
                continue
            values = [getattr(row, name) for row in selected]
            if any(value is None for value in values):
                missing = missing or name
                continue
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, Decimal))
                or (isinstance(value, Decimal) and not value.is_finite())
                or value < 0
                for value in values
            ):
                invalid = invalid or name
                continue
            totals.append((name, _decimal_string(_exact_sum(values))))
        reason = (
            "invalid_input"
            if invalid
            else "incompatible_currency"
            if cross_currency
            else "missing_input"
            if missing
            else None
        )
        support = invalid or ("currency" if cross_currency else missing)
        if reason is None:
            values_by_name = dict(totals)
            if Decimal(values_by_name[denominator]) == 0:
                reason, support = "zero_denominator", denominator
        value = None
        if reason is None:
            values_by_name = dict(totals)
            value = _decimal_string(
                Decimal(values_by_name[numerator])
                * multiplier
                / Decimal(values_by_name[denominator])
            )
    return CalculatedMetric(
        metric,
        scope,
        group,
        campaign,
        currency,
        represented,
        start,
        end,
        tuple(totals),
        value,
        unit if reason is None else None,
        reason,
        support,
    )


def calculate_kpis(
    rows: Sequence[CanonicalInput],
    *,
    period_start: date,
    period_end: date,
) -> tuple[CalculatedMetric, ...]:
    if not rows or any(row.row_date < period_start or row.row_date > period_end for row in rows):
        raise ValueError("canonical rows are absent or outside the confirmed period")
    groups: list[tuple[str, str, str | None, list[CanonicalInput]]] = [
        ("report", "report", None, list(rows))
    ]
    for name in sorted({row.campaign_name for row in rows}):
        groups.append(
            (
                "campaign",
                campaign_identity(name),
                name,
                [row for row in rows if row.campaign_name == name],
            )
        )
    results: list[CalculatedMetric] = []
    for scope, group, campaign, selected in groups:
        currencies = sorted({row.currency for row in selected})
        results.append(
            _one(selected, "ctr", scope, group, campaign, None, period_start, period_end)
        )
        for metric in METRIC_ORDER[1:]:
            if len(currencies) > 1:
                results.append(
                    _one(selected, metric, scope, group, campaign, None, period_start, period_end)
                )
            for currency in currencies:
                results.append(
                    _one(
                        selected, metric, scope, group, campaign, currency, period_start, period_end
                    )
                )
    return tuple(results)


@dataclass(frozen=True, slots=True)
class ComparableResult:
    identity: str
    metric_name: str
    value: str | None
    unit: str | None
    period_start: date
    period_end: date
    boundary_policy: str
    calculation_version: str
    definition: str
    mapping_revision: int
    normalization_policy_version: str
    scope: str
    group_identity: str
    currency: str | None


def compare_periods(left: ComparableResult, right: ComparableResult) -> dict[str, object]:
    attributes = (
        "metric_name",
        "unit",
        "boundary_policy",
        "calculation_version",
        "definition",
        "mapping_revision",
        "normalization_policy_version",
        "scope",
        "group_identity",
        "currency",
    )
    mismatches = [name for name in attributes if getattr(left, name) != getattr(right, name)]
    if (left.period_end - left.period_start).days != (right.period_end - right.period_start).days:
        mismatches.append("duration")
    if left.value is None or right.value is None:
        mismatches.append("availability")
    if mismatches:
        return {
            "availability": "unavailable",
            "unavailable_reason": "incomparable_period",
            "details": sorted(mismatches),
        }
    assert left.value is not None and right.value is not None
    with localcontext() as context:
        context.prec = 38
        difference = Decimal(right.value) - Decimal(left.value)
    return {
        "availability": "available",
        "value": _decimal_string(difference),
        "unit": left.unit,
        "left_result_id": left.identity,
        "right_result_id": right.identity,
    }
