"""Dataset route shapes and owner-safe errors."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.dataset_schemas import (
    AvailableMetric,
    CanonicalRowDetail,
    DatasetDetail,
    UnavailableMetric,
)
from app.api.datasets import services
from app.api.dependencies import AuthenticatedPrincipal, get_authenticated_principal
from app.core.config import Settings
from app.core.resources import ResourceClients
from app.domain.assets import ResourceNotFound
from app.main import create_app


class FakeClients:
    object_storage = object()

    async def close(self) -> None:
        return None


class FakeDatasetReads:
    def __init__(self, owner: UUID, report: UUID, dataset: UUID) -> None:
        self.owner, self.report, self.dataset = owner, report, dataset

    def check(self, owner: UUID, report: UUID, dataset: UUID | None = None) -> None:
        if owner != self.owner or report != self.report or dataset not in (None, self.dataset):
            raise ResourceNotFound

    async def detail(self, owner: UUID, report: UUID, dataset: UUID | None = None) -> DatasetDetail:
        self.check(owner, report, dataset)
        return DatasetDetail(
            id=self.dataset,
            report_id=report,
            source_id=uuid4(),
            confirmation_id=uuid4(),
            canonical_data_identity="a" * 64,
            normalization_policy_version="normalize-v1",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            total_records=2,
            accepted_row_count=2,
            rejected_row_count=0,
            row_count_explanation="All source records were accepted, including warned duplicates.",
            currencies=["USD"],
            metric_result_set_id=uuid4(),
        )

    async def rows(self, owner: UUID, report: UUID, dataset: UUID, offset: int, limit: int):
        self.check(owner, report, dataset)
        rows = [
            CanonicalRowDetail(
                id=uuid4(),
                source_record_index=index,
                date=date(2026, 1, 1),
                campaign_name="A",
                currency="USD",
                impressions=100,
                clicks=10,
                spend="0.30",
                leads=None,
            )
            for index in (1, 2)
        ]
        page = rows[offset : offset + limit]
        return page, offset + len(page) if offset + len(page) < 2 else None, 2

    async def metrics(
        self,
        owner: UUID,
        report: UUID,
        dataset: UUID,
        scope: str | None,
        campaign_name: str | None,
        currency: str | None,
    ):
        self.check(owner, report, dataset)
        common = dict(
            id=uuid4(),
            metric_name="ctr",
            scope="report",
            group_identity="report",
            campaign_name=None,
            currency=None,
            represented_currencies=["USD"],
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            canonical_data_identity="a" * 64,
            calculation_version="kpi-v1",
            calculated_at=datetime.now(UTC),
            inputs={"clicks": "20", "impressions": "200"},
        )
        return [
            AvailableMetric.model_validate(
                {**common, "availability": "available", "value": "10", "unit": "percent"}
            )
        ], uuid4()


def test_dataset_reads_and_safe_errors(settings: Settings) -> None:
    owner, report, dataset = uuid4(), uuid4(), uuid4()
    fake = FakeDatasetReads(owner, report, dataset)
    app = create_app(settings, client_factory=lambda _: cast(ResourceClients, FakeClients()))
    app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(id=owner)
    app.dependency_overrides[services] = lambda: fake
    base = f"/api/v1/reports/{report}/datasets"
    with TestClient(app) as client:
        current = client.get(base + "/current")
        assert current.status_code == 200
        assert current.json()["data"]["accepted_row_count"] == 2
        assert client.get(base + f"/{dataset}").json()["data"]["id"] == str(dataset)
        page = client.get(base + f"/{dataset}/rows?offset=0&limit=1")
        assert page.json()["data"][0]["source_record_index"] == 1
        assert page.json()["next_offset"] == 1
        assert "object_key" not in page.text
        metrics = client.get(base + f"/{dataset}/metrics")
        assert metrics.status_code == 200
        assert metrics.json()["data"][0]["value"] == "10"
        assert "unavailable_reason" not in metrics.json()["data"][0]
        invalid = client.get(base + f"/{dataset}/rows?offset=-1")
        assert invalid.status_code == 422
        absent = client.get(base + f"/{uuid4()}/rows")
        foreign = client.get(f"/api/v1/reports/{uuid4()}/datasets/{dataset}/rows")
        assert absent.status_code == foreign.status_code == 404
        assert absent.json()["error"]["code"] == foreign.json()["error"]["code"]
        assert absent.json()["error"]["message"] == foreign.json()["error"]["message"]
        assert absent.json()["error"]["code"] == "resource_not_found"
    assert "/api/v1/reports/{report_id}/datasets/{dataset_id}/metrics" in app.openapi()["paths"]


def test_unavailable_variant_omits_value_and_unit() -> None:
    result = UnavailableMetric.model_validate(
        {
            "id": uuid4(),
            "metric_name": "cpc",
            "scope": "report",
            "group_identity": "report",
            "campaign_name": None,
            "currency": None,
            "represented_currencies": ["USD", "EUR"],
            "period_start": date(2026, 1, 1),
            "period_end": date(2026, 1, 31),
            "canonical_data_identity": "a" * 64,
            "calculation_version": "kpi-v1",
            "calculated_at": datetime.now(UTC),
            "inputs": {"clicks": "7"},
            "availability": "unavailable",
            "unavailable_reason": "incompatible_currency",
            "supporting_field": "currency",
        }
    )
    assert "value" not in result.model_dump()
    assert "unit" not in result.model_dump()
