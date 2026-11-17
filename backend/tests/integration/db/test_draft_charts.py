from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DraftChart, DraftChartMetricReference, ReportDraft
from app.db.repositories import ConcurrencyConflict, save_draft_charts
from app.db.snapshots import ChartSnapshot
from tests.integration.db.test_datasets_and_metrics import seed_dataset_metric_aggregate

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_chart_edits_are_ordered_revisioned_and_metric_scoped(
    db_session: AsyncSession,
) -> None:
    report, _dataset, _row, _metric_set, metric = await seed_dataset_metric_aggregate(
        db_session, subject="chart-owner"
    )
    draft = await db_session.scalar(select(ReportDraft).where(ReportDraft.report_id == report.id))
    assert draft is not None
    charts = [
        ChartSnapshot(
            chart_type="bar", title="Click rate", scope="report", metric_result_ids=(metric.id,)
        ),
        ChartSnapshot(
            chart_type="table",
            title="Metric detail",
            scope="report",
            metric_result_ids=(metric.id,),
        ),
    ]
    revision = await save_draft_charts(
        db_session,
        owner_id=report.owner_id,
        report_id=report.id,
        draft_id=draft.id,
        expected_revision=1,
        charts=charts,
    )
    assert revision == 2
    await db_session.refresh(draft)
    assert draft.revision == 2
    saved = list(
        await db_session.scalars(
            select(DraftChart).where(DraftChart.draft_id == draft.id).order_by(DraftChart.ordinal)
        )
    )
    assert [chart.title for chart in saved] == ["Click rate", "Metric detail"]
    references = list(
        await db_session.scalars(
            select(DraftChartMetricReference).where(
                DraftChartMetricReference.chart_id == saved[0].id
            )
        )
    )
    assert [reference.metric_result_id for reference in references] == [metric.id]

    with pytest.raises(ConcurrencyConflict):
        await save_draft_charts(
            db_session,
            owner_id=report.owner_id,
            report_id=report.id,
            draft_id=draft.id,
            expected_revision=1,
            charts=charts,
        )
    with pytest.raises(ValueError, match="not current"):
        await save_draft_charts(
            db_session,
            owner_id=report.owner_id,
            report_id=report.id,
            draft_id=draft.id,
            expected_revision=2,
            charts=[
                ChartSnapshot(
                    chart_type="bar",
                    title="Wrong metric",
                    scope="report",
                    metric_result_ids=(uuid4(),),
                )
            ],
        )
    with pytest.raises(ValidationError):
        await save_draft_charts(
            db_session,
            owner_id=report.owner_id,
            report_id=report.id,
            draft_id=draft.id,
            expected_revision=2,
            charts=[
                {
                    "chart_type": "bar",
                    "title": "Override",
                    "scope": "report",
                    "metric_result_ids": [str(metric.id)],
                    "value": 999,
                }
            ],
        )
    await db_session.refresh(draft)
    assert draft.revision == 2
    assert (
        len(
            list(
                await db_session.scalars(select(DraftChart).where(DraftChart.draft_id == draft.id))
            )
        )
        == 2
    )
