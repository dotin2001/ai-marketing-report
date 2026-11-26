from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    get_report_services,
)
from app.api.report_schemas import (
    Chart,
    Claim,
    DraftDetail,
    DraftReference,
    Page,
    Period,
    ReportDetail,
    ReportSummary,
    UpdateDraftRequest,
)
from app.core.config import Settings
from app.core.resources import ResourceClients
from app.db.repositories import ConcurrencyConflict
from app.domain.reports import (
    DraftValidationError,
    InvalidCursor,
    ReportNotFound,
    validate_idempotency_key,
)
from app.main import create_app


class FakeClients:
    object_storage = object()

    async def close(self) -> None:
        return None


class FakeReports:
    def __init__(self) -> None:
        self.id = uuid4()
        self.draft_id = uuid4()
        self.calls = 0
        self.revision = 1
        self.name = "Quarterly report"
        self.objectives = ["Explain performance"]
        self.claims: list[Claim] = []
        self.charts: list[Chart] = []

    def detail_model(self) -> ReportDetail:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        draft = DraftDetail(
            id=self.draft_id,
            report_id=self.id,
            revision=self.revision,
            objectives=self.objectives,
            claims=self.claims,
            charts=self.charts,
            current_metric_result_set_id=None,
            current_analysis_result_id=None,
            created_at=now,
            updated_at=now,
        )
        return ReportDetail(
            id=self.id,
            name=self.name,
            period=Period.model_validate({"start_date": "2026-01-01", "end_date": "2026-01-31"}),
            stage="created",
            active_draft=draft,
            objectives=self.objectives,
            current_source_id=None,
            current_dataset_id=None,
            current_analysis_result_id=None,
            current_metric_result_set_id=None,
            latest_version=None,
            created_at=now,
            updated_at=now,
        )

    async def create(self, owner_id: UUID, command: Any, key: str) -> tuple[ReportDetail, bool]:
        validate_idempotency_key(key)
        self.calls += 1
        self.name = command.name
        self.objectives = command.objectives
        return self.detail_model(), self.calls > 1

    async def detail(self, owner_id: UUID, report_id: UUID) -> ReportDetail:
        if report_id != self.id:
            raise ReportNotFound
        return self.detail_model()

    async def list(
        self, owner_id: UUID, limit: int, cursor: str | None
    ) -> tuple[list[ReportSummary], Page]:
        if cursor:
            raise InvalidCursor
        detail = self.detail_model()
        return [
            ReportSummary(
                id=detail.id,
                name=detail.name,
                period=detail.period,
                stage=detail.stage,
                active_draft=DraftReference(
                    id=detail.active_draft.id, revision=detail.active_draft.revision
                ),
                current_source_id=None,
                current_dataset_id=None,
                current_analysis_result_id=None,
                latest_version=None,
                created_at=detail.created_at,
                updated_at=detail.updated_at,
            )
        ], Page(limit=limit, has_more=False, next_cursor=None)

    async def update_metadata(self, owner_id: UUID, report_id: UUID, command: Any) -> ReportDetail:
        if report_id != self.id:
            raise ReportNotFound
        if command.name is not None and command.name != self.name:
            self.name = command.name
            self.revision += 1
        return self.detail_model()

    async def update_objectives(self, owner_id: UUID, report_id: UUID, command: Any) -> DraftDetail:
        if report_id != self.id:
            raise ReportNotFound
        self.objectives = command.objectives
        self.revision += 1
        return self.detail_model().active_draft

    async def update_draft(
        self, owner_id: UUID, report_id: UUID, command: UpdateDraftRequest
    ) -> DraftDetail:
        if report_id != self.id:
            raise ReportNotFound
        if command.expected_revision != self.revision:
            raise ConcurrencyConflict
        if command.claims is not None:
            self.claims = [
                Claim(
                    id=uuid4(),
                    ordinal=index,
                    content=item.content,
                    classification=item.classification,
                    source_id=item.source_id,
                )
                for index, item in enumerate(command.claims, start=1)
            ]
        if command.charts is not None:
            if any(item.metric_result_ids[0] == UUID(int=0) for item in command.charts):
                raise DraftValidationError(["charts", 0, "metric_result_ids", 0])
            self.charts = [
                Chart(
                    id=uuid4(),
                    ordinal=index,
                    chart_type=item.chart_type,
                    title=item.title,
                    scope=item.scope,
                    x_label=item.x_label,
                    y_label=item.y_label,
                    metric_result_ids=item.metric_result_ids,
                )
                for index, item in enumerate(command.charts, start=1)
            ]
        if command.objectives is not None:
            self.objectives = command.objectives
        self.revision += 1
        return self.detail_model().active_draft


def client_for(
    settings: Settings, service: FakeReports, *, authenticated: bool = True
) -> TestClient:
    app = create_app(settings, client_factory=lambda _: cast(ResourceClients, FakeClients()))
    app.dependency_overrides[get_report_services] = lambda: service
    if authenticated:
        app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(
            id=uuid4()
        )
    return TestClient(app)


def payload() -> dict[str, object]:
    return {
        "name": " Quarterly report ",
        "period": {"start_date": "2026-01-01", "end_date": "2026-01-31"},
        "objectives": [" Explain performance "],
    }


def test_runtime_create_list_detail_and_updates(settings: Settings) -> None:
    service = FakeReports()
    with client_for(settings, service) as client:
        created = client.post(
            "/api/v1/reports", json=payload(), headers={"Idempotency-Key": "create-1"}
        )
        assert created.status_code == 201
        assert created.json()["data"]["active_draft"]["revision"] == 1
        assert created.json()["data"]["stage"] == "created"
        assert created.json()["data"]["created_at"].endswith("Z")
        assert "owner_id" not in created.text and "object_key" not in created.text
        replay = client.post(
            "/api/v1/reports", json=payload(), headers={"Idempotency-Key": "create-1"}
        )
        assert replay.status_code == 201 and replay.headers["Idempotency-Replayed"] == "true"
        listed = client.get("/api/v1/reports")
        assert listed.status_code == 200
        assert listed.json()["page"] == {"limit": 25, "has_more": False, "next_cursor": None}
        assert client.get("/api/v1/reports?limit=1").json()["page"]["limit"] == 1
        assert client.get("/api/v1/reports?limit=100").json()["page"]["limit"] == 100
        detail = client.get(f"/api/v1/reports/{service.id}")
        assert detail.status_code == 200
        renamed = client.patch(
            f"/api/v1/reports/{service.id}", json={"expected_revision": 1, "name": " New name "}
        )
        assert renamed.status_code == 200 and renamed.json()["data"]["name"] == "New name"
        edited = client.patch(
            f"/api/v1/reports/{service.id}/draft",
            json={"expected_revision": 2, "objectives": [" New goal "]},
        )
        assert edited.status_code == 200 and edited.json()["data"]["revision"] == 3
        metric_id = uuid4()
        saved = client.patch(
            f"/api/v1/reports/{service.id}/draft",
            json={
                "expected_revision": 3,
                "claims": [{"content": " User claim ", "classification": "user_claim"}],
                "charts": [
                    {
                        "chart_type": "bar",
                        "title": " CTR ",
                        "scope": "report",
                        "metric_result_ids": [str(metric_id)],
                    }
                ],
            },
        )
        assert saved.status_code == 200 and saved.json()["data"]["revision"] == 4
        assert saved.json()["data"]["claims"][0]["content"] == "User claim"
        assert saved.json()["data"]["charts"][0]["metric_result_ids"] == [str(metric_id)]
        reopened = client.get(f"/api/v1/reports/{service.id}").json()["data"]["active_draft"]
        assert reopened["charts"] == saved.json()["data"]["charts"]
        assert reopened["claims"] == saved.json()["data"]["claims"]
        stale = client.patch(
            f"/api/v1/reports/{service.id}/draft",
            json={"expected_revision": 3, "claims": []},
        )
        assert (stale.status_code, stale.json()["error"]["code"]) == (409, "revision_conflict")
        invalid_reference = client.patch(
            f"/api/v1/reports/{service.id}/draft",
            json={
                "expected_revision": 4,
                "charts": [
                    {
                        "chart_type": "bar",
                        "title": "CTR",
                        "scope": "report",
                        "metric_result_ids": [str(UUID(int=0))],
                    }
                ],
            },
        )
        assert invalid_reference.status_code == 422
        assert invalid_reference.json()["error"]["details"][0]["path"] == [
            "charts",
            0,
            "metric_result_ids",
            0,
        ]
        assert (
            client.get(f"/api/v1/reports/{service.id}").json()["data"]["active_draft"]["revision"]
            == 4
        )


def test_invalid_requests_have_safe_error_details(settings: Settings) -> None:
    service = FakeReports()
    with client_for(settings, service) as client:
        invalid = client.post(
            "/api/v1/reports",
            json={**payload(), "objectives": ["SECRET-VALUE", " "]},
            headers={"Idempotency-Key": "create-1", "X-Request-ID": "r1"},
        )
        assert invalid.status_code == 422
        body = invalid.json()["error"]
        assert body["code"] == "validation_failed" and body["request_id"] == "r1"
        assert body["details"][0]["path"] == ["objectives", 1]
        assert "SECRET-VALUE" not in invalid.text and 'detail"' not in invalid.text
        assert service.calls == 0
        bad_key = client.post(
            "/api/v1/reports", json=payload(), headers={"Idempotency-Key": "bad key"}
        )
        assert bad_key.status_code == 400 and bad_key.json()["error"]["code"] == "invalid_request"
        missing_key = client.post("/api/v1/reports", json=payload())
        assert missing_key.status_code == 422 and missing_key.json()["error"]["details"][0][
            "path"
        ] == ["Idempotency-Key"]
        assert client.get("/api/v1/reports?limit=0").json()["error"]["code"] == "validation_failed"
        assert client.get("/api/v1/reports?limit=101").status_code == 422
        assert client.get("/api/v1/reports?limit=1.5").status_code == 422
        assert (
            client.get("/api/v1/reports?cursor=tampered").json()["error"]["code"]
            == "invalid_cursor"
        )
        assert (
            client.get(f"/api/v1/reports/{uuid4()}").json()["error"]["code"] == "resource_not_found"
        )
        invalid_metadata = client.patch(
            f"/api/v1/reports/{service.id}",
            json={"expected_revision": 1, "name": "Should not save", "stage": "versioned"},
        )
        assert invalid_metadata.status_code == 422
        assert invalid_metadata.json()["error"]["details"][0]["path"] == ["stage"]
        invalid_objective = client.patch(
            f"/api/v1/reports/{service.id}/draft",
            json={"expected_revision": 1, "objectives": [" "]},
        )
        assert invalid_objective.status_code == 422
        assert service.name == "Quarterly report"
        assert service.objectives == ["Explain performance"]
        assert (
            client.patch(
                f"/api/v1/reports/{service.id}/draft",
                json={
                    "expected_revision": 1,
                    "claims": [],
                    "current_analysis_result_id": str(uuid4()),
                },
            ).json()["error"]["code"]
            == "validation_failed"
        )
        missing = client.patch(
            f"/api/v1/reports/{uuid4()}/draft",
            json={"expected_revision": 1, "claims": []},
        )
        assert missing.status_code == 404


def test_unauthenticated_and_openapi(settings: Settings) -> None:
    service = FakeReports()
    with client_for(settings, service, authenticated=False) as client:
        assert client.get("/api/v1/reports").json()["error"]["code"] == "unauthenticated"
        schema = client.get("/openapi.json").json()
    routes = schema["paths"]
    assert "post" in routes["/api/v1/reports"]
    assert "patch" in routes["/api/v1/reports/{report_id}"]
    assert "patch" in routes["/api/v1/reports/{report_id}/draft"]
    patch = routes["/api/v1/reports/{report_id}/draft"]["patch"]
    assert patch["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/UpdateDraftRequest"
    )
    assert patch["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/DraftEnvelope"
    )
    assert "422" in routes["/api/v1/reports"]["post"]["responses"]
    assert (
        "Idempotency-Replayed" in routes["/api/v1/reports"]["post"]["responses"]["201"]["headers"]
    )
    error_schema = routes["/api/v1/reports"]["post"]["responses"]["409"]["content"][
        "application/json"
    ]["schema"]
    assert error_schema["$ref"].endswith("/ErrorEnvelope")
    assert set(schema["components"]["schemas"]["ErrorBody"]["properties"]) == {
        "code",
        "message",
        "request_id",
        "retryable",
        "details",
        "context",
    }
