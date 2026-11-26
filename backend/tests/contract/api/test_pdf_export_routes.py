"""PDF export routes expose the strict owner-safe public contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    get_pdf_export_services,
)
from app.api.report_schemas import Page
from app.api.version_schemas import PdfExportDetail, PdfExportSummary
from app.core.config import Settings
from app.core.resources import ResourceClients
from app.db.repositories import ConcurrencyConflict, IdempotencyConflict
from app.domain.assets import ResourceNotFound
from app.domain.reports import InvalidCursor
from app.main import create_app


class FakeClients:
    object_storage = object()

    async def close(self) -> None:
        pass


class FakeExports:
    def __init__(self) -> None:
        self.report_id, self.version_id, self.export_id = uuid4(), uuid4(), uuid4()
        self.state = "queued"
        self.calls = 0

    def model(self) -> PdfExportDetail:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        return PdfExportDetail.model_validate(
            {
                "id": self.export_id,
                "report_id": self.report_id,
                "version_id": self.version_id,
                "template_version": "report-v1",
                "input_identity": "a" * 64,
                "state": self.state,
                "attempt_count": 1,
                "created_at": now,
                "updated_at": now,
                "failure": {
                    "code": "render_failed",
                    "message": "Rendering failed.",
                    "retryable": True,
                }
                if self.state == "failed"
                else None,
                "attempts": [
                    {
                        "ordinal": 1,
                        "state": self.state,
                        "queued_at": now,
                        "started_at": now if self.state != "queued" else None,
                        "finished_at": now if self.state in {"failed", "succeeded"} else None,
                        "failure": {
                            "code": "render_failed",
                            "message": "Rendering failed.",
                            "retryable": True,
                        }
                        if self.state == "failed"
                        else None,
                    }
                ],
                "file": {
                    "filename": "report.pdf",
                    "content_type": "application/pdf",
                    "byte_size": 5,
                    "checksum": "b" * 64,
                    "download_available": True,
                }
                if self.state == "succeeded"
                else None,
            }
        )

    async def create(self, owner: UUID, report: UUID, version: UUID, command: object, key: str):
        self._check(report, version)
        if key == "conflict":
            raise IdempotencyConflict
        if key == "bad":
            raise ValueError
        self.calls += 1
        return self.model(), self.calls > 1

    async def list(self, owner: UUID, report: UUID, version: UUID, limit: int, cursor: str | None):
        self._check(report, version)
        if cursor:
            raise InvalidCursor
        return [
            PdfExportSummary.model_validate(self.model().model_dump(exclude={"attempts", "file"}))
        ], Page(limit=limit, has_more=False, next_cursor=None)

    async def detail(self, owner: UUID, report: UUID, version: UUID, export: UUID):
        self._check(report, version)
        if export != self.export_id:
            raise ResourceNotFound
        return self.model()

    async def retry(
        self, owner: UUID, report: UUID, version: UUID, export: UUID, command: object, key: str
    ):
        await self.detail(owner, report, version, export)
        if key == "stale":
            raise ConcurrencyConflict
        return self.model(), key == "replay"

    def _check(self, report: UUID, version: UUID) -> None:
        if report != self.report_id or version != self.version_id:
            raise ResourceNotFound


def test_pdf_export_routes_and_openapi(settings: Settings) -> None:
    fake = FakeExports()
    app = create_app(settings, client_factory=lambda _: cast(ResourceClients, FakeClients()))
    app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(
        id=uuid4()
    )
    app.dependency_overrides[get_pdf_export_services] = lambda: fake
    base = f"/api/v1/reports/{fake.report_id}/versions/{fake.version_id}/pdf-exports"
    with TestClient(app) as client:
        for state in ("queued", "running", "succeeded", "failed"):
            fake.state = state
            result = client.get(f"{base}/{fake.export_id}")
            assert result.status_code == 200
            assert result.json()["data"]["state"] == state
            assert "object_key" not in result.text and "bucket" not in result.text
            assert (result.json()["data"]["file"] is not None) == (state == "succeeded")
        fake.state = "queued"
        assert (
            client.post(
                base, json={"template_version": "report-v1"}, headers={"Idempotency-Key": "ok"}
            ).status_code
            == 202
        )
        replay = client.post(
            base, json={"template_version": "report-v1"}, headers={"Idempotency-Key": "ok"}
        )
        assert replay.headers["Idempotency-Replayed"] == "true"
        assert client.get(base).status_code == 200
        assert client.get(base, params={"cursor": "wrong"}).status_code == 400
        assert (
            client.post(
                base,
                json={"template_version": "report-v1"},
                headers={"Idempotency-Key": "conflict"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                base, json={"template_version": "report-v1"}, headers={"Idempotency-Key": "bad"}
            ).status_code
            == 400
        )
        assert (
            client.post(
                base, json={"template_version": "unknown"}, headers={"Idempotency-Key": "ok"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"{base}/{fake.export_id}/retry",
                json={"input_identity": "a" * 64, "expected_attempt_count": 1},
                headers={"Idempotency-Key": "retry"},
            ).status_code
            == 202
        )
        assert (
            client.post(
                f"{base}/{fake.export_id}/retry",
                json={"input_identity": "a" * 64, "expected_attempt_count": 1},
                headers={"Idempotency-Key": "stale"},
            ).status_code
            == 409
        )
        assert client.get(f"{base}/{uuid4()}").status_code == 404
        missing_report = client.get(
            f"/api/v1/reports/{uuid4()}/versions/{fake.version_id}/pdf-exports"
        )
        missing_version = client.get(
            f"/api/v1/reports/{fake.report_id}/versions/{uuid4()}/pdf-exports"
        )
        assert missing_report.status_code == missing_version.status_code == 404
        assert missing_report.json()["error"]["code"] == missing_version.json()["error"]["code"]
        schema = client.get("/openapi.json").json()
        assert schema["paths"]["/api/v1/reports/{report_id}/versions/{version_id}/pdf-exports"][
            "post"
        ]["responses"]["202"]
    app.dependency_overrides.clear()
    with TestClient(app) as client:
        assert client.get(base).status_code == 401
