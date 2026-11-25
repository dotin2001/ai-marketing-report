from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.context import (
    MAX_OBJECTIVES,
    ExactTotal,
    Objective,
    Period,
    PreparedContext,
    PreparedMetric,
)
from app.ai.output import NarrativeItem, NumericAssertion, StructuredOutput, validate_output


def context() -> PreparedContext:
    owner, report, job, source, confirmation, dataset, result_set, draft, metric_id = (
        uuid4() for _ in range(9)
    )
    period = Period(start=date(2026, 1, 1), end=date(2026, 1, 31))
    return PreparedContext(
        version="analysis-context-v1",
        owner_id=owner,
        report_id=report,
        job_id=job,
        source_id=source,
        source_checksum_sha256="d" * 64,
        confirmation_id=confirmation,
        dataset_id=dataset,
        canonical_data_identity="a" * 64,
        result_set_id=result_set,
        numeric_source_identity="b" * 64,
        semantic_input_identity="c" * 64,
        draft_id=draft,
        draft_revision=1,
        objectives_revision=1,
        period=period,
        represented_currencies=["EUR", "USD"],
        objectives=[Objective(ordinal=1, content="Explain acquisition")],
        metrics=[
            PreparedMetric(
                id=metric_id,
                name="cpc",
                availability="available",
                value="0.10",
                unit="USD/click",
                unavailable_reason=None,
                supporting_field=None,
                scope="currency",
                group_identity="currency",
                campaign_name=None,
                period=period,
                currency="USD",
                represented_currencies=["USD"],
                inputs=[ExactTotal(ordinal=1, name="spend", value="0.30")],
                calculation_version="kpi-v1",
                result_set_id=result_set,
                numeric_source_identity="b" * 64,
            )
        ],
    )


def output(item: NarrativeItem | None = None) -> StructuredOutput:
    return StructuredOutput(
        summary=[
            item
            or NarrativeItem(
                ordinal=1,
                classification="observation",
                content="Acquisition remained efficient.",
            )
        ],
        findings=[],
        anomalies=[],
        recommendations=[],
        data_gaps=[],
    )


def validated(response: StructuredOutput, prepared: PreparedContext) -> None:
    validate_output(
        response,
        prepared,
        model_identifier="fake",
        prompt_version="v1",
        request_provenance="test",
    )


def test_context_rejects_nonfinite_and_malformed_values() -> None:
    for value in ("NaN", "Infinity", "-Infinity", "bad", " 1"):
        with pytest.raises(ValidationError):
            ExactTotal(ordinal=1, name="spend", value=value)
    with pytest.raises(ValidationError):
        Period(start=date(2026, 2, 1), end=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        Objective(ordinal=1, content=" ")
    prepared = context()
    at_limit = PreparedContext.model_validate(
        {
            **prepared.model_dump(),
            "objectives": [{"ordinal": n, "content": "x"} for n in range(1, MAX_OBJECTIVES + 1)],
        }
    )
    assert len(at_limit.objectives) == MAX_OBJECTIVES
    with pytest.raises(ValidationError):
        PreparedContext.model_validate(
            {
                **prepared.model_dump(),
                "objectives": [
                    {"ordinal": n, "content": "x"} for n in range(1, MAX_OBJECTIVES + 2)
                ],
            }
        )


def test_five_sections_and_strict_shape() -> None:
    prepared = context()
    validated(output(), prepared)
    payload = output().model_dump()
    for altered in (
        {key: value for key, value in payload.items() if key != "data_gaps"},
        {**payload, "unexpected": []},
        {**payload, "summary": []},
        {**payload, "summary": [{**payload["summary"][0], "ordinal": 2}]},
        {**payload, "summary": [{**payload["summary"][0], "classification": "fact"}]},
    ):
        with pytest.raises(ValidationError):
            StructuredOutput.model_validate(altered)


def test_grounded_assertions_and_unavailable_reasons() -> None:
    prepared = context()
    metric = prepared.metrics[0]
    assertion = NumericAssertion(
        metric_id=metric.id,
        value="0.10",
        unit="USD/click",
        scope="currency",
        period=prepared.period,
        currency="USD",
    )
    item = NarrativeItem(
        ordinal=1,
        classification="observation",
        content="Spend efficiency was stable.",
        metric_ids=[metric.id],
        numeric_assertions=[assertion],
    )
    validated(output(item), prepared)
    for changed in (
        {"value": "0.11"},
        {"unit": "EUR/click"},
        {"scope": "report"},
        {"currency": "EUR"},
        {"period": Period(start=date(2026, 2, 1), end=date(2026, 2, 28))},
    ):
        bad = assertion.model_copy(update=changed)
        with pytest.raises(ValueError):
            validated(output(item.model_copy(update={"numeric_assertions": [bad]})), prepared)
    with pytest.raises(ValueError):
        validated(output(item.model_copy(update={"metric_ids": [uuid4()]})), prepared)
    with pytest.raises(ValidationError):
        NarrativeItem(ordinal=1, classification="observation", content="CPC was 0.10 USD.")
    unavailable = metric.model_copy(
        update={
            "availability": "unavailable",
            "value": None,
            "unit": None,
            "unavailable_reason": "zero_denominator",
        }
    )
    limited = prepared.model_copy(update={"metrics": [unavailable]})
    gap = NarrativeItem(
        ordinal=1,
        classification="observation",
        content="The metric cannot be calculated.",
        metric_ids=[metric.id],
        unavailable_reasons={metric.id: "zero_denominator"},
    )
    validated(
        StructuredOutput(
            summary=output().summary,
            findings=[],
            anomalies=[],
            recommendations=[],
            data_gaps=[gap],
        ),
        limited,
    )
    with pytest.raises(ValueError):
        validated(output(gap), limited)


def test_mixed_currency_and_unavailable_metrics_remain_distinct() -> None:
    prepared = context()
    usd = prepared.metrics[0]
    eur = PreparedMetric.model_validate(
        {
            **usd.model_dump(),
            **{
                "id": uuid4(),
                "value": "0.20",
                "unit": "EUR/click",
                "currency": "EUR",
                "represented_currencies": ["EUR"],
            },
        }
    )
    combined = PreparedMetric.model_validate(
        {
            **usd.model_dump(),
            **{
                "id": uuid4(),
                "scope": "report",
                "group_identity": "report",
                "currency": None,
                "availability": "unavailable",
                "value": None,
                "unit": None,
                "unavailable_reason": "incompatible_currency",
                "represented_currencies": ["EUR", "USD"],
            },
        }
    )
    mixed = PreparedContext.model_validate(
        {
            **prepared.model_dump(),
            "metrics": [eur.model_dump(), usd.model_dump(), combined.model_dump()],
        }
    )
    assert [(m.currency, m.value) for m in mixed.metrics[:2]] == [("EUR", "0.20"), ("USD", "0.10")]
    assert combined.value is None
    assert combined.unavailable_reason == "incompatible_currency"
    assert combined.represented_currencies == ["EUR", "USD"]


@pytest.mark.parametrize("text", ["Q4 results", "Growth was 10%", "USD $5", "2026-01-01"])
def test_free_text_numeric_claims_are_rejected(text: str) -> None:
    with pytest.raises(ValidationError):
        NarrativeItem(ordinal=1, classification="observation", content=text)
