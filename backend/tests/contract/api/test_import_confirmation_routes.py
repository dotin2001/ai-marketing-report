"""Confirmed import API contract and safe error envelopes."""

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
from app.api.source_schemas import ColumnMapping, ConfirmedImportDetail, ConfirmImportRequest
from app.api.sources import confirmation_services
from app.core.config import Settings
from app.core.resources import ResourceClients
from app.db.repositories import IdempotencyConflict
from app.domain.assets import ResourceNotFound
from app.domain.import_confirmation import (
    BlockedImportValidation,
    StaleImportInput,
    WarningAcknowledgementRequired,
)
from app.main import create_app


class FakeClients:
    object_storage = object()

    async def close(self) -> None:
        return None


class FakeConfirmation:
    def __init__(self, owner: UUID, report: UUID, source: UUID) -> None:
        self.owner, self.report, self.source = owner, report, source
        self.validation = uuid4()
        self.warning = uuid4()
        self.confirmation = uuid4()
        self.dataset = uuid4()
        self.seen: dict[str, ConfirmImportRequest] = {}

    async def confirm(
        self,
        owner: UUID,
        report: UUID,
        source: UUID,
        command: ConfirmImportRequest,
        key: str,
        assets: Any,
    ) -> tuple[ConfirmedImportDetail, bool]:
        if (owner, report, source) != (self.owner, self.report, self.source):
            raise ResourceNotFound
        if key in self.seen and self.seen[key] != command:
            raise IdempotencyConflict("key conflict")
        if command.validation_id != self.validation:
            raise BlockedImportValidation
        if command.expected_revision != 1:
            raise StaleImportInput("stale")
        if command.acknowledged_warning_ids != [self.warning]:
            raise WarningAcknowledgementRequired
        replayed = key in self.seen
        self.seen[key] = command
        detail = ConfirmedImportDetail(
            id=self.confirmation,
            report_id=report,
            source_id=source,
            validation_id=self.validation,
            configuration_id=uuid4(),
            revision=1,
            confirmed_by=owner,
            dataset_id=self.dataset,
            canonical_data_identity="a" * 64,
            source_checksum_sha256="b" * 64,
            normalization_policy_version="normalize-v1",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            period_revision=1,
            row_count=2,
            currencies=["USD"],
            mappings=[ColumnMapping(source_column_ordinal=0, canonical_field="date")],
        )
        return detail, replayed


def test_import_confirmation_contract_and_owner_safe_errors(settings: Settings) -> None:
    owner, report, source = uuid4(), uuid4(), uuid4()
    fake = FakeConfirmation(owner, report, source)
    app = create_app(settings, client_factory=lambda _: cast(ResourceClients, FakeClients()))
    app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(id=owner)
    app.dependency_overrides[get_asset_services] = lambda: object()
    app.dependency_overrides[confirmation_services] = lambda: fake
    base = f"/api/v1/reports/{report}/sources/{source}"
    body = {
        "validation_id": str(fake.validation),
        "expected_revision": 1,
        "acknowledged_warning_ids": [str(fake.warning)],
    }
    with TestClient(app) as client:
        path = base + "/import-configuration/confirm"
        success = client.post(path, json=body, headers={"Idempotency-Key": "confirm-key"})
        assert success.status_code == 200
        assert success.json()["data"]["dataset_id"] == str(fake.dataset)
        assert success.json()["data"]["row_count"] == 2
        replay = client.post(
            base + "/confirm", json=body, headers={"Idempotency-Key": "confirm-key"}
        )
        assert replay.status_code == 200
        assert replay.headers["Idempotency-Replayed"] == "true"
        assert replay.json()["data"]["id"] == success.json()["data"]["id"]
        conflict = client.post(
            path, json={**body, "expected_revision": 2}, headers={"Idempotency-Key": "confirm-key"}
        )
        assert (conflict.status_code, conflict.json()["error"]["code"]) == (
            409,
            "idempotency_conflict",
        )
        blocked = client.post(
            path,
            json={**body, "validation_id": str(uuid4())},
            headers={"Idempotency-Key": "blocked-key"},
        )
        assert (blocked.status_code, blocked.json()["error"]["code"]) == (422, "validation_failed")
        warning = client.post(
            path,
            json={**body, "acknowledged_warning_ids": []},
            headers={"Idempotency-Key": "warning-key"},
        )
        assert (warning.status_code, warning.json()["error"]["code"]) == (
            409,
            "warning_acknowledgement_required",
        )
        stale = client.post(
            path, json={**body, "expected_revision": 2}, headers={"Idempotency-Key": "stale-key"}
        )
        assert (stale.status_code, stale.json()["error"]["code"]) == (409, "stale_input")
        assert client.post(path, json=body).status_code == 422
        assert (
            client.post(
                path,
                json={**body, "object_key": "private"},
                headers={"Idempotency-Key": "bad-body"},
            ).status_code
            == 422
        )
        absent = client.post(
            f"/api/v1/reports/{uuid4()}/sources/{source}/confirm",
            json=body,
            headers={"Idempotency-Key": "absent"},
        )
        foreign = client.post(
            f"/api/v1/reports/{report}/sources/{uuid4()}/confirm",
            json=body,
            headers={"Idempotency-Key": "foreign"},
        )
        assert absent.status_code == foreign.status_code == 404
        assert absent.json()["error"]["code"] == foreign.json()["error"]["code"]
        for response in (success, blocked, warning, stale, absent, foreign):
            for secret in ("object_key", "raw-cell", "credential", "provider_error"):
                assert secret not in response.text
        spec = client.get("/openapi.json").json()["paths"]
        operation = spec["/api/v1/reports/{report_id}/sources/{source_id}/confirm"]["post"]
        assert "ConfirmedImportEnvelope" in str(operation["responses"]["200"])
        assert "Idempotency-Key" in str(operation["parameters"])
        assert "409" in operation["responses"] and "422" in operation["responses"]
