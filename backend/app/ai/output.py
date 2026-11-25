"""Provider-independent narrative shape and numeric grounding."""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.ai.context import Period, PreparedContext, StrictModel

SECTIONS = ("summary", "findings", "anomalies", "recommendations", "data_gaps")
NUMERIC_TEXT = re.compile(r"\d|[%$€£¥]", re.UNICODE)
MAX_ITEMS_PER_SECTION = 20
MAX_ITEM_CHARS = 2000


class NumericAssertion(StrictModel):
    metric_id: UUID
    value: str
    unit: str
    scope: Literal["report", "currency", "campaign"]
    period: Period
    currency: str | None


class NarrativeItem(StrictModel):
    ordinal: int = Field(ge=1)
    classification: Literal["observation", "hypothesis"]
    content: str = Field(min_length=1, max_length=MAX_ITEM_CHARS)
    metric_ids: list[UUID] = Field(default_factory=list, max_length=200)
    numeric_assertions: list[NumericAssertion] = Field(default_factory=list, max_length=200)
    unavailable_reasons: dict[UUID, str] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def safe_text(cls, value: str) -> str:
        if not value.strip() or NUMERIC_TEXT.search(value):
            raise ValueError("blank or unsupported numeric content")
        return value

    @model_validator(mode="after")
    def unique_references(self) -> NarrativeItem:
        if len(self.metric_ids) != len(set(self.metric_ids)):
            raise ValueError("duplicate metric reference")
        if len(self.numeric_assertions) != len({a.metric_id for a in self.numeric_assertions}):
            raise ValueError("duplicate numeric assertion")
        return self


class StructuredOutput(StrictModel):
    summary: list[NarrativeItem] = Field(min_length=1, max_length=MAX_ITEMS_PER_SECTION)
    findings: list[NarrativeItem] = Field(max_length=MAX_ITEMS_PER_SECTION)
    anomalies: list[NarrativeItem] = Field(max_length=MAX_ITEMS_PER_SECTION)
    recommendations: list[NarrativeItem] = Field(max_length=MAX_ITEMS_PER_SECTION)
    data_gaps: list[NarrativeItem] = Field(max_length=MAX_ITEMS_PER_SECTION)

    @model_validator(mode="after")
    def stable_order(self) -> StructuredOutput:
        for section in SECTIONS:
            items = getattr(self, section)
            if [item.ordinal for item in items] != list(range(1, len(items) + 1)):
                raise ValueError("non-contiguous item order")
        return self


class ValidatedOutput(StrictModel):
    model_identifier: str = Field(min_length=1, max_length=255)
    prompt_version: str = Field(min_length=1, max_length=64)
    request_provenance: str = Field(min_length=1, max_length=500)
    semantic_input_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    numeric_source_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    sections: StructuredOutput


class RunnerOutput(StrictModel):
    model_identifier: str = Field(min_length=1, max_length=255)
    prompt_version: str = Field(min_length=1, max_length=64)
    request_provenance: str = Field(min_length=1, max_length=500)
    response: StructuredOutput


def validate_output(
    response: StructuredOutput,
    context: PreparedContext,
    *,
    model_identifier: str,
    prompt_version: str,
    request_provenance: str,
) -> ValidatedOutput:
    """Attach trusted provenance after checking every referenced numeric fact."""
    metrics = {metric.id: metric for metric in context.metrics}
    for section in SECTIONS:
        for item in getattr(response, section):
            refs = set(item.metric_ids)
            if set(item.unavailable_reasons) - refs:
                raise ValueError("unreferenced limitation")
            if {a.metric_id for a in item.numeric_assertions} - refs:
                raise ValueError("unreferenced numeric assertion")
            for metric_id in refs:
                metric = metrics.get(metric_id)
                if metric is None:
                    raise ValueError("foreign metric reference")
                reason = item.unavailable_reasons.get(metric_id)
                if metric.availability == "unavailable":
                    if section != "data_gaps" or reason != metric.unavailable_reason:
                        raise ValueError("invalid unavailable metric reference")
                elif reason is not None:
                    raise ValueError("available metric has a limitation reason")
            for assertion in item.numeric_assertions:
                metric = metrics[assertion.metric_id]
                if (
                    metric.availability != "available"
                    or assertion.value != metric.value
                    or assertion.unit != metric.unit
                    or assertion.scope != metric.scope
                    or assertion.period != metric.period
                    or assertion.currency != metric.currency
                ):
                    raise ValueError("numeric assertion differs from prepared metric")
    return ValidatedOutput(
        model_identifier=model_identifier,
        prompt_version=prompt_version,
        request_provenance=request_provenance,
        semantic_input_identity=context.semantic_input_identity,
        numeric_source_identity=context.numeric_source_identity,
        sections=response,
    )
