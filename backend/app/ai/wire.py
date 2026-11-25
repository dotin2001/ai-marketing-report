"""OpenAI-compatible five-section DTO and conversion to trusted domain output."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.ai.context import Period
from app.ai.output import NarrativeItem, NumericAssertion, StructuredOutput


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WirePeriod(WireModel):
    start: str
    end: str


class WireNumericAssertion(WireModel):
    metric_id: str
    value: str
    unit: str
    scope: Literal["report", "currency", "campaign"]
    period: WirePeriod
    currency: str | None


class WireUnavailableReason(WireModel):
    metric_id: str
    reason: str


class WireItem(WireModel):
    ordinal: int
    classification: Literal["observation", "hypothesis"]
    content: str
    metric_ids: list[str]
    numeric_assertions: list[WireNumericAssertion]
    unavailable_reasons: list[WireUnavailableReason]


class WireOutput(WireModel):
    summary: list[WireItem]
    findings: list[WireItem]
    anomalies: list[WireItem]
    recommendations: list[WireItem]
    data_gaps: list[WireItem]


def _period(value: WirePeriod) -> Period:
    if not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", part) for part in (value.start, value.end)):
        raise ValueError("invalid wire period")
    return Period(start=date.fromisoformat(value.start), end=date.fromisoformat(value.end))


def _item(value: WireItem) -> NarrativeItem:
    reasons = [(UUID(item.metric_id), item.reason) for item in value.unavailable_reasons]
    if len(reasons) != len({metric_id for metric_id, _ in reasons}):
        raise ValueError("duplicate unavailable reason")
    return NarrativeItem(
        ordinal=value.ordinal,
        classification=value.classification,
        content=value.content,
        metric_ids=[UUID(metric_id) for metric_id in value.metric_ids],
        numeric_assertions=[
            NumericAssertion(
                metric_id=UUID(item.metric_id),
                value=item.value,
                unit=item.unit,
                scope=item.scope,
                period=_period(item.period),
                currency=item.currency,
            )
            for item in value.numeric_assertions
        ],
        unavailable_reasons=dict(reasons),
    )


def convert_wire(value: WireOutput) -> StructuredOutput:
    return StructuredOutput(
        summary=[_item(item) for item in value.summary],
        findings=[_item(item) for item in value.findings],
        anomalies=[_item(item) for item in value.anomalies],
        recommendations=[_item(item) for item in value.recommendations],
        data_gaps=[_item(item) for item in value.data_gaps],
    )
