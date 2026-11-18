from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.report_schemas import (
    CreateReportRequest,
    DraftDetail,
    MetadataPatchRequest,
    ObjectivesPatchRequest,
    Period,
    ReportDetail,
)


def command(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "name": "  Annual report  ",
        "period": {"start_date": "2026-01-01", "end_date": "2026-12-31"},
        "objectives": ["  Explain performance  "],
    }
    value.update(overrides)
    return value


def test_creation_normalizes_boundary_values() -> None:
    model = CreateReportRequest.model_validate(
        command(name=" " + "A" * 200 + " ", objectives=[" x " * 666 + "x"])
    )
    assert model.name == "A" * 200
    assert len(model.objectives[0]) == 1998
    assert model.period.start_date.isoformat() == "2026-01-01"


@pytest.mark.parametrize(
    ("overrides", "path"),
    [
        ({"name": " "}, ("name",)),
        ({"name": "x" * 201}, ("name",)),
        ({"objectives": []}, ("objectives",)),
        ({"objectives": ["ok", " "]}, ("objectives", 1)),
        ({"objectives": ["x"] * 21}, ("objectives",)),
        ({"period": {"start_date": "2026-02-01", "end_date": "2026-01-01"}}, ("period",)),
        (
            {"period": {"start_date": "01/01/2026", "end_date": "2026-01-31"}},
            ("period", "start_date"),
        ),
        ({"private": "secret"}, ("private",)),
    ],
)
def test_creation_rejects_invalid_fields(
    overrides: dict[str, object], path: tuple[object, ...]
) -> None:
    with pytest.raises(ValidationError) as error:
        CreateReportRequest.model_validate(command(**overrides))
    assert path in [tuple(issue["loc"]) for issue in error.value.errors()]


def test_patch_models_require_revision_and_effective_field_shape() -> None:
    assert MetadataPatchRequest.model_validate({"expected_revision": 1, "name": " x "}).name == "x"
    assert ObjectivesPatchRequest.model_validate(
        {"expected_revision": 1, "objectives": [" x "]}
    ).objectives == ["x"]
    for payload in (
        {"expected_revision": 1},
        {"expected_revision": 0, "name": "x"},
        {"expected_revision": 1, "period": {"start_date": "2026-01-01"}},
    ):
        with pytest.raises(ValidationError):
            MetadataPatchRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        Period.model_validate({"start_date": "2026-01-01T00:00:00", "end_date": "2026-01-01"})


def test_public_detail_serialization_excludes_private_fields() -> None:
    report_id, draft_id = uuid4(), uuid4()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    draft = DraftDetail(
        id=draft_id,
        report_id=report_id,
        revision=1,
        objectives=["Goal"],
        current_metric_result_set_id=None,
        current_analysis_result_id=None,
        created_at=now,
        updated_at=now,
    )
    detail = ReportDetail(
        id=report_id,
        name="Report",
        period=Period.model_validate({"start_date": "2026-01-01", "end_date": "2026-01-01"}),
        stage="created",
        active_draft=draft,
        objectives=["Goal"],
        current_source_id=None,
        current_dataset_id=None,
        current_analysis_result_id=None,
        current_metric_result_set_id=None,
        latest_version=None,
        created_at=now,
        updated_at=now,
    )
    data = detail.model_dump(mode="json")
    assert data["created_at"] == "2026-01-01T00:00:00Z"
    assert data["id"] == str(report_id)
    assert "owner_id" not in data
    assert "object_key" not in data
