"""Public import-review route contracts and safe errors."""

from __future__ import annotations

from datetime import date
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import (
    AuthenticatedPrincipal,
    get_asset_services,
    get_authenticated_principal,
)
from app.api.source_schemas import (
    ImportConfigurationDetail,
    ImportConfigurationRequest,
    ImportValidationDetail,
    ValidateImportRequest,
    ValidationIssue,
)
from app.api.sources import review_services
from app.core.config import Settings
from app.core.resources import ResourceClients
from app.db.repositories import ConcurrencyConflict
from app.domain.assets import ResourceNotFound
from app.domain.import_review import InvalidMapping, ReviewResponseTooLarge
from app.main import create_app


class FakeClients:
    object_storage = object()

    async def close(self) -> None:
        return None


class FakeReview:
    def __init__(self, owner_id: UUID, report_id: UUID, source_id: UUID) -> None:
        self.owner_id, self.report_id, self.source_id = owner_id, report_id, source_id
        self.configuration_id = uuid4()
        self.validation_id = uuid4()
        self.issue_id = uuid4()
        self.revision = 0
        self.too_large = False

    def authorize(self, owner_id: UUID, report_id: UUID, source_id: UUID) -> None:
        if (owner_id, report_id, source_id) != (self.owner_id, self.report_id, self.source_id):
            raise ResourceNotFound

    async def put_configuration(
        self,
        owner_id: UUID,
        report_id: UUID,
        source_id: UUID,
        command: ImportConfigurationRequest,
        assets: Any,
    ) -> ImportConfigurationDetail:
        self.authorize(owner_id, report_id, source_id)
        if command.expected_revision != self.revision:
            raise ConcurrencyConflict("stale")
        if len({m.source_column_ordinal for m in command.mappings}) != len(command.mappings):
            raise InvalidMapping(
                [
                    {
                        "code": "duplicate_mapping",
                        "message": "A column is mapped twice.",
                        "path": ["mappings", 1, "source_column_ordinal"],
                    }
                ]
            )
        self.revision += 1
        return ImportConfigurationDetail(
            id=self.configuration_id,
            report_id=report_id,
            source_id=source_id,
            revision=self.revision,
            normalization_policy_version=command.normalization_policy_version,
            date_format=command.date_format,
            mappings=command.mappings,
        )

    async def validate(
        self,
        owner_id: UUID,
        report_id: UUID,
        source_id: UUID,
        command: ValidateImportRequest,
        assets: Any,
    ) -> ImportValidationDetail:
        self.authorize(owner_id, report_id, source_id)
        if command.expected_revision != self.revision:
            raise ConcurrencyConflict("stale")
        if self.too_large:
            raise ReviewResponseTooLarge
        return ImportValidationDetail(
            id=self.validation_id,
            report_id=report_id,
            source_id=source_id,
            configuration_id=self.configuration_id,
            revision=self.revision,
            source_checksum_sha256="a" * 64,
            normalization_policy_version="normalize-v1",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            period_revision=1,
            total_records=2,
            error_count=1,
            warning_count=0,
            confirmation_blocked=True,
            issues=[
                ValidationIssue(
                    id=self.issue_id,
                    code="invalid_count",
                    severity="error",
                    message="The count must be a plain whole number.",
                    canonical_field="clicks",
                    source_column_ordinal=3,
                    source_record_index=2,
                    related_record_index=None,
                )
            ],
        )


def test_import_review_routes_safe_contract_and_openapi(settings: Settings) -> None:
    owner, report, source = uuid4(), uuid4(), uuid4()
    fake = FakeReview(owner, report, source)
    app = create_app(settings, client_factory=lambda _: cast(ResourceClients, FakeClients()))
    app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(id=owner)
    app.dependency_overrides[get_asset_services] = lambda: object()
    app.dependency_overrides[review_services] = lambda: fake
    base = f"/api/v1/reports/{report}/sources/{source}"
    mapping = {
        "expected_revision": 0,
        "normalization_policy_version": "normalize-v1",
        "mappings": [{"source_column_ordinal": 3, "canonical_field": "clicks"}],
    }
    with TestClient(app) as client:
        created = client.put(base + "/import-configuration", json=mapping)
        assert created.status_code == 200
        assert created.json()["data"]["revision"] == 1
        assert created.json()["data"]["confirmed"] is False
        validation = client.post(
            base + "/import-configuration/validate", json={"expected_revision": 1}
        )
        assert validation.status_code == 200
        alias = client.post(base + "/validate", json={"expected_revision": 1})
        assert alias.status_code == 200
        assert alias.json() == validation.json()
        assert validation.json()["data"]["confirmation_blocked"] is True
        assert validation.json()["data"]["issues"][0]["source_record_index"] == 2
        assert validation.json()["data"]["total_records"] == 2
        fake.too_large = True
        oversized = client.post(
            base + "/import-configuration/validate", json={"expected_revision": 1}
        )
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "validation_response_too_large"
        fake.too_large = False
        for secret in ("bad-cell", "object_key", "credential"):
            assert secret not in validation.text
        stale = client.post(base + "/import-configuration/validate", json={"expected_revision": 2})
        assert (stale.status_code, stale.json()["error"]["code"]) == (409, "revision_conflict")
        duplicate = client.put(
            base + "/import-configuration",
            json={
                **mapping,
                "expected_revision": 1,
                "mappings": [
                    {"source_column_ordinal": 0, "canonical_field": "date"},
                    {"source_column_ordinal": 0, "canonical_field": "clicks"},
                ],
            },
        )
        assert duplicate.status_code == 422
        assert duplicate.json()["error"]["details"][0]["path"] == [
            "mappings",
            1,
            "source_column_ordinal",
        ]
        absent = client.post(
            f"/api/v1/reports/{uuid4()}/sources/{source}/import-configuration/validate",
            json={"expected_revision": 1},
        )
        foreign = client.post(
            f"/api/v1/reports/{report}/sources/{uuid4()}/import-configuration/validate",
            json={"expected_revision": 1},
        )
        assert absent.status_code == foreign.status_code == 404
        assert absent.json()["error"]["code"] == foreign.json()["error"]["code"]
        paths = client.get("/openapi.json").json()["paths"]
        configuration_path = "/api/v1/reports/{report_id}/sources/{source_id}/import-configuration"
        assert "put" in paths[configuration_path]
        validation_path = (
            "/api/v1/reports/{report_id}/sources/{source_id}/import-configuration/validate"
        )
        assert "post" in paths[validation_path]
        assert "post" in paths["/api/v1/reports/{report_id}/sources/{source_id}/validate"]
        assert "ImportValidationEnvelope" in str(paths[validation_path]["post"]["responses"]["200"])
