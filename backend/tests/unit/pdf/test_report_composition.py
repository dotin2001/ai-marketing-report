from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.db.models import ReportVersion
from app.db.repositories import report_snapshot_identity
from app.db.snapshots import ReportVersionSnapshotV2
from app.pdf.errors import PdfRenderFailure
from app.pdf.html import render_report_html
from app.pdf.version import SavedVersion
from app.pdf.view_model import build_report_view


def test_version_binding_accepts_both_schemas_and_rejects_invalid_envelopes(
    version_factory: Callable[..., SavedVersion],
) -> None:
    for schema in (1, 2):
        version = version_factory(schema=schema)
        assert version.validated_snapshot().schema_version == schema
        invalids = (
            replace(version, report_id=uuid4()),
            replace(version, template_version="report-v2"),
            replace(version, snapshot_identity=b"x" * 32),
            replace(version, snapshot_schema_version=9),
            replace(version, snapshot_json=b"{invalid"),
            replace(
                version,
                snapshot_json=version.snapshot_json.replace(
                    b'"schema_version":2', b'"schema_version":9'
                ),
            )
            if schema == 2
            else replace(
                version,
                snapshot_json=version.snapshot_json.replace(
                    b'"schema_version":1', b'"schema_version":9'
                ),
            ),
        )
        for invalid in invalids:
            with pytest.raises(PdfRenderFailure) as error:
                invalid.validated_snapshot()
            assert error.value.code == "invalid_snapshot"
            assert "script" not in str(error.value)


def test_allowlisted_model_and_html_preserve_saved_content(
    version_factory: Callable[..., SavedVersion],
) -> None:
    version = version_factory()
    view = build_report_view(version)
    assert view.version_number == 3 and view.period_start.isoformat() == "2026-01-01"
    assert [metric.value for metric in view.metrics] == ["1.2500", "2.5000", None]
    assert view.metrics[-1].reason == "Zero denominator"
    assert [section.title for section in view.narrative] == ["Insights", "Recommendations"]
    assert [item.content for item in view.narrative[0].items] == [
        "Có thể cải thiện.",
        "Độ tăng trưởng ổn định.",
    ]
    assert view.narrative[0].items[0].classification == "Hypothesis"
    assert view.narrative[1].items[0].classification == "Hypothesis"
    html = render_report_html(version)
    for expected in (
        "Báo cáo hiệu quả",
        "2026-01-01",
        "Version 3",
        "1.2500",
        "Zero denominator",
        "Insights",
        "Recommendations",
        "Dữ liệu có giới hạn.",
        "Unvalidated user claim",
    ):
        assert expected in html
    assert "&lt;script&gt;alert" in html and "<script>alert" not in html
    assert "object_key" not in html and "inline_text" not in html


def test_immutable_envelope_detaches_from_record_and_normalizes_time(
    version_factory: Callable[..., SavedVersion],
) -> None:
    version = version_factory()
    record = ReportVersion(
        id=version.version_id,
        owner_id=uuid4(),
        report_id=version.report_id,
        version_number=version.version_number,
        source_draft_id=uuid4(),
        source_draft_revision=1,
        created_at=datetime(2026, 2, 1, 7, tzinfo=timezone(timedelta(hours=7))),
        snapshot_identity=version.snapshot_identity,
        snapshot_schema_version=version.snapshot_schema_version,
        template_version=version.template_version,
        snapshot=json.loads(version.snapshot_json),
    )
    frozen = SavedVersion.from_record(record)
    record.snapshot["report_name"] = "Later mutable change"
    assert frozen.validated_snapshot().report_name != record.snapshot["report_name"]
    assert build_report_view(frozen).created_at.isoformat() == "2026-02-01T00:00:00+00:00"


def test_chart_modes_use_only_saved_comparable_metrics(
    version_factory: Callable[..., SavedVersion],
) -> None:
    version = version_factory()
    view = build_report_view(version)
    assert [chart.display_type for chart in view.charts] == ["bar", "line", "table"]
    assert [row.bar_width for row in view.charts[0].rows] == [50, 100]
    assert view.charts[1].line_points is not None
    assert view.charts[2].rows[-1].reason == "Zero denominator"
    data = json.loads(version.snapshot_json)
    data["metrics"][1]["unit"] = "USD"
    changed = ReportVersionSnapshotV2.model_validate(data)
    incompatible = replace(
        version,
        snapshot_json=changed.model_dump_json().encode(),
        snapshot_identity=report_snapshot_identity(changed),
    )
    assert [chart.display_type for chart in build_report_view(incompatible).charts] == [
        "table",
        "table",
        "table",
    ]
    data["metrics"][1]["unit"] = "%"
    data["metrics"][1]["scope"] = "currency:USD"
    changed = ReportVersionSnapshotV2.model_validate(data)
    incompatible_scope = replace(
        version,
        snapshot_json=changed.model_dump_json().encode(),
        snapshot_identity=report_snapshot_identity(changed),
    )
    assert build_report_view(incompatible_scope).charts[0].display_type == "table"


def test_legacy_and_text_only_omit_absent_sections(
    version_factory: Callable[..., SavedVersion],
) -> None:
    legacy = version_factory(schema=1)
    text_only = version_factory(text_only=True)
    assert build_report_view(legacy).charts == ()
    assert build_report_view(text_only).metrics == ()
    for version in (legacy, text_only):
        html = render_report_html(version)
        assert "<h2>Charts</h2>" not in html
    assert "<h2>Key performance indicators</h2>" not in render_report_html(text_only)


def test_hostile_labels_are_inert_text(version_factory: Callable[..., SavedVersion]) -> None:
    version = version_factory()
    data = json.loads(version.snapshot_json)
    hostile = '<img src="https://example.invalid/collect"><script>fetch("https://example.invalid")</script>'
    data["narrative"][0]["content"] = hostile
    data["charts"][0]["title"] = hostile
    snapshot = ReportVersionSnapshotV2.model_validate(data)
    changed = replace(
        version,
        snapshot_json=snapshot.model_dump_json().encode(),
        snapshot_identity=report_snapshot_identity(snapshot),
    )
    html = render_report_html(changed)
    assert "&lt;img src=&#34;https://example.invalid/collect&#34;&gt;" in html
    assert '<img src="https://example.invalid/collect">' not in html
    assert "<script>fetch" not in html
