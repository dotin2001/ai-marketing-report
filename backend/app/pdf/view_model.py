"""Allowlisted, presentation-only projection of a saved version."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.db.snapshots import (
    AnalysisItemSnapshot,
    ChartSnapshot,
    MetricSnapshot,
    NarrativeSnapshot,
    ReportVersionSnapshotV2,
)
from app.pdf.version import SavedVersion

SECTION_TITLES = {
    "summary": "Summary",
    "findings": "Insights",
    "anomalies": "Anomalies",
    "recommendations": "Recommendations",
    "data_gaps": "Data gaps",
}
CLASSIFICATION_LABELS = {
    "observation": "Observation",
    "hypothesis": "Hypothesis",
    "user_claim": "Unvalidated user claim",
}
REASON_LABELS = {
    "missing_input": "Missing input",
    "zero_denominator": "Zero denominator",
    "invalid_input": "Invalid input",
    "incompatible_currency": "Incompatible currencies",
    "incomparable_period": "Incomparable periods",
}


@dataclass(frozen=True, slots=True)
class MetricView:
    metric_id: UUID
    label: str
    availability: str
    value: str | None
    unit: str | None
    reason: str | None
    scope: str
    currency: str | None
    exact_inputs: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ChartRow:
    label: str
    value: str | None
    unit: str | None
    reason: str | None
    bar_width: int | None = None


@dataclass(frozen=True, slots=True)
class ChartView:
    title: str
    chart_type: Literal["bar", "line", "table"]
    display_type: Literal["bar", "line", "table"]
    scope: str
    x_label: str | None
    y_label: str | None
    rows: tuple[ChartRow, ...]
    line_points: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class NarrativeView:
    content: str
    classification: str


@dataclass(frozen=True, slots=True)
class NarrativeSectionView:
    title: str
    items: tuple[NarrativeView, ...]


@dataclass(frozen=True, slots=True)
class ReportView:
    report_name: str
    period_start: date
    period_end: date
    version_id: UUID
    version_number: int
    created_at: datetime
    objectives: tuple[str, ...]
    metrics: tuple[MetricView, ...]
    charts: tuple[ChartView, ...]
    narrative: tuple[NarrativeSectionView, ...]
    limitations: tuple[str, ...]
    claims: tuple[str, ...]


def _metric(metric: MetricSnapshot) -> MetricView:
    return MetricView(
        metric_id=metric.metric_result_id,
        label=metric.name.upper(),
        availability=metric.availability,
        value=metric.value,
        unit=metric.unit,
        reason=REASON_LABELS[metric.unavailable_reason] if metric.unavailable_reason else None,
        scope=metric.scope,
        currency=metric.currency,
        exact_inputs=tuple(sorted(metric.exact_inputs.items())),
    )


def _chart(chart: ChartSnapshot, metrics: dict[UUID, MetricView]) -> ChartView:
    selected = tuple(metrics[metric_id] for metric_id in chart.metric_result_ids)
    comparable = (
        chart.chart_type != "table"
        and all(metric.value is not None and metric.unit is not None for metric in selected)
        and len({metric.unit for metric in selected}) == 1
        and len({metric.currency for metric in selected}) == 1
        and all(metric.scope == chart.scope for metric in selected)
        and all(Decimal(metric.value or "0") >= 0 for metric in selected)
    )
    maximum = max((Decimal(metric.value or "0") for metric in selected), default=Decimal(0))
    comparable = comparable and maximum > 0
    rows = tuple(
        ChartRow(
            label=metric.label,
            value=metric.value,
            unit=metric.unit,
            reason=metric.reason,
            bar_width=(int(Decimal(metric.value or "0") / maximum * 100) if comparable else None),
        )
        for metric in selected
    )
    points = None
    if comparable and chart.chart_type == "line":
        points = " ".join(
            f"{40 + (index * 920 // max(len(selected) - 1, 1))},"
            f"{180 - int(Decimal(metric.value or '0') / maximum * 150)}"
            for index, metric in enumerate(selected)
        )
    display_type: Literal["bar", "line", "table"] = chart.chart_type if comparable else "table"
    return ChartView(
        title=chart.title,
        chart_type=chart.chart_type,
        display_type=display_type,
        scope=chart.scope,
        x_label=chart.x_label,
        y_label=chart.y_label,
        rows=rows,
        line_points=points,
        note="Values are shown as saved; a plotted scale is unavailable."
        if not comparable
        else None,
    )


def build_report_view(version: SavedVersion) -> ReportView:
    frozen = version.validated_snapshot()
    metrics = tuple(_metric(metric) for metric in frozen.metrics)
    by_id = {metric.metric_id: metric for metric in metrics}
    charts = (
        tuple(_chart(chart, by_id) for chart in frozen.charts)
        if isinstance(frozen, ReportVersionSnapshotV2)
        else ()
    )
    sections: list[NarrativeSectionView] = []
    for section, title in SECTION_TITLES.items():
        edited = sorted(
            (item for item in frozen.narrative if item.section == section),
            key=lambda item: item.ordinal,
        )
        saved_items: tuple[NarrativeSnapshot | AnalysisItemSnapshot, ...] = (
            tuple(edited)
            if edited
            else tuple(
                sorted(
                    (item for item in frozen.analysis.items if item.section == section),
                    key=lambda item: item.ordinal,
                )
            )
            if frozen.analysis is not None
            else ()
        )
        if saved_items:
            sections.append(
                NarrativeSectionView(
                    title=title,
                    items=tuple(
                        NarrativeView(
                            content=item.content,
                            classification=CLASSIFICATION_LABELS.get(
                                item.classification or "", "Saved narrative"
                            ),
                        )
                        for item in saved_items
                    ),
                )
            )
    return ReportView(
        report_name=frozen.report_name,
        period_start=frozen.period_start,
        period_end=frozen.period_end,
        version_id=version.version_id,
        version_number=version.version_number,
        created_at=version.created_at.astimezone(UTC),
        objectives=frozen.objectives,
        metrics=metrics,
        charts=charts,
        narrative=tuple(sections),
        limitations=frozen.limitations,
        claims=tuple(claim.content for claim in sorted(frozen.claims, key=lambda c: c.ordinal)),
    )
