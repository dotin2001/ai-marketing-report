from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    get_version_services,
)
from app.api.report_schemas import DraftDetail, Page
from app.api.version_schemas import VersionDetail, VersionSummary
from app.core.config import Settings
from app.core.resources import ResourceClients
from app.db.repositories import ConcurrencyConflict, IdempotencyConflict
from app.domain.reports import InvalidCursor, ReportNotFound
from app.domain.version_service import VersionNotFound
from app.main import create_app


class FakeClients:
    object_storage = object()

    async def close(self) -> None:
        pass


class FakeVersions:
    def __init__(self) -> None:
        self.report_id, self.version_id, self.draft_id = uuid4(), uuid4(), uuid4()
        self.calls = 0
        self.restore_calls = 0

    def detail_model(self) -> VersionDetail:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        return VersionDetail.model_validate(
            {
                "id": self.version_id,
                "report_id": self.report_id,
                "version_number": 1,
                "source_draft_id": self.draft_id,
                "source_draft_revision": 1,
                "template_version": "report-v1",
                "snapshot_schema_version": 2,
                "snapshot_identity": "a" * 64,
                "dataset_id": None,
                "metric_result_set_id": None,
                "analysis_result_id": None,
                "latest_pdf_export": None,
                "created_at": now,
                "snapshot": {
                    "schema_version": 2,
                    "report_id": self.report_id,
                    "report_name": "Report",
                    "period_start": "2026-01-01",
                    "period_end": "2026-01-31",
                    "objectives": ["Goal"],
                    "source": {
                        "source_id": uuid4(),
                        "source_type": "text",
                        "checksum_sha256": "b" * 64,
                        "byte_size": 4,
                        "media_type": "text/plain",
                    },
                    "metrics": [],
                    "narrative": [],
                    "limitations": [],
                    "claims": [],
                    "template_version": "report-v1",
                },
            }
        )

    async def create(
        self, owner: UUID, report: UUID, revision: int, key: str
    ) -> tuple[VersionDetail, bool]:
        if report != self.report_id:
            raise ReportNotFound
        if key == "conflict":
            raise IdempotencyConflict
        if revision != 1:
            raise ConcurrencyConflict
        self.calls += 1
        return self.detail_model(), self.calls > 1

    async def list(
        self, owner: UUID, report: UUID, limit: int, cursor: str | None
    ) -> tuple[list[VersionSummary], Page]:
        if cursor:
            raise InvalidCursor
        if report != self.report_id:
            raise ReportNotFound
        return [
            VersionSummary.model_validate(self.detail_model().model_dump(exclude={"snapshot"}))
        ], Page(limit=limit, has_more=False, next_cursor=None)

    async def detail(self, owner: UUID, report: UUID, version: UUID) -> VersionDetail:
        if report != self.report_id or version != self.version_id:
            raise VersionNotFound
        return self.detail_model()

    async def restore(
        self, owner: UUID, report: UUID, version: UUID, draft: UUID, revision: int, key: str
    ) -> tuple[DraftDetail, bool]:
        if version != self.version_id or report != self.report_id:
            raise VersionNotFound
        if revision != 1 or draft != self.draft_id:
            raise ConcurrencyConflict
        self.restore_calls += 1
        now = datetime(2026, 1, 1, tzinfo=UTC)
        return DraftDetail(
            id=uuid4(),
            report_id=report,
            revision=1,
            objectives=["Goal"],
            current_metric_result_set_id=None,
            current_analysis_result_id=None,
            created_at=now,
            updated_at=now,
        ), self.restore_calls > 1


def test_version_routes_and_openapi(settings: Settings) -> None:
    fake = FakeVersions()
    app = create_app(settings, client_factory=lambda _: cast(ResourceClients, FakeClients()))
    app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(
        id=uuid4()
    )
    app.dependency_overrides[get_version_services] = lambda: fake
    base = f"/api/v1/reports/{fake.report_id}/versions"
    with TestClient(app) as client:
        created = client.post(
            base, json={"expected_draft_revision": 1}, headers={"Idempotency-Key": "k"}
        )
        assert created.status_code == 201
        assert created.json()["data"]["snapshot"]["source"]["checksum_sha256"] == "b" * 64
        assert created.json()["data"]["created_at"].endswith("Z")
        assert (
            client.post(
                base, json={"expected_draft_revision": 1}, headers={"Idempotency-Key": "k"}
            ).headers["Idempotency-Replayed"]
            == "true"
        )
        assert client.get(base).json()["data"][0]["version_number"] == 1
        assert client.get(f"{base}/{fake.version_id}").status_code == 200
        restored = client.post(
            f"{base}/{fake.version_id}/restore",
            json={"expected_draft_id": str(fake.draft_id), "expected_draft_revision": 1},
            headers={"Idempotency-Key": "restore"},
        )
        assert restored.status_code == 200 and restored.json()["data"]["objectives"] == ["Goal"]
        assert client.get(f"{base}?cursor=bad").json()["error"]["code"] == "invalid_cursor"
        assert client.get(f"/api/v1/reports/{uuid4()}/versions").status_code == 404
        assert client.get(f"{base}/{uuid4()}").status_code == 404
        assert (
            client.post(
                base, json={"expected_draft_revision": 2}, headers={"Idempotency-Key": "k2"}
            ).status_code
            == 409
        )
        assert (
            client.post(
                base, json={"expected_draft_revision": 1}, headers={"Idempotency-Key": "conflict"}
            ).json()["error"]["code"]
            == "idempotency_conflict"
        )
        assert (
            client.post(
                base,
                json={"expected_draft_revision": 1, "owner_id": str(uuid4())},
                headers={"Idempotency-Key": "k3"},
            ).status_code
            == 422
        )
        paths = app.openapi()["paths"]
        assert "/api/v1/reports/{report_id}/versions" in paths
        assert "/api/v1/reports/{report_id}/versions/{version_id}/restore" in paths
