from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import (
    AuthenticatedPrincipal,
    get_asset_services,
    get_authenticated_principal,
)
from app.api.source_schemas import SourceDetail, SourcePreview
from app.api.sources import services
from app.core.config import Settings
from app.core.resources import ResourceClients
from app.db.repositories import IdempotencyConflict
from app.domain.assets import ResourceNotFound
from app.main import create_app
from app.processing.source_envelope import (
    SourceEnvelopeError,
    csv_preview,
    parse_csv,
    text_preview,
)


class FakeClients:
    object_storage = object()

    async def close(self) -> None:
        return None


class FakeSources:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.report_id = uuid4()
        self.source_id = uuid4()
        self.calls = 0
        self.last_content: bytes | str = b""
        self.fingerprints: dict[tuple[str, str], bytes | str] = {}

    def detail_model(self, source_type: str) -> SourceDetail:
        return SourceDetail(
            id=self.source_id,
            report_id=self.report_id,
            source_type=source_type,
            byte_size=len(self.last_content),
            checksum_sha256="0" * 64,
            media_type="text/csv" if source_type == "csv" else "text/plain",
            encoding="utf-8",
            original_filename_untrusted="../unsafe.csv" if source_type == "csv" else None,
            display_filename="unsafe.csv" if source_type == "csv" else None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    async def attach_text(
        self, owner_id: UUID, report_id: UUID, content: str, key: str
    ) -> tuple[SourceDetail, bool]:
        if report_id != self.report_id:
            raise ResourceNotFound
        if ("text", key) in self.fingerprints and self.fingerprints[("text", key)] != content:
            raise IdempotencyConflict
        self.fingerprints[("text", key)] = content
        if len(content.encode()) > self.settings.source_text_max_bytes:
            raise SourceEnvelopeError("payload_too_large")
        self.calls += 1
        self.last_content = content
        return self.detail_model("text"), self.calls > 1

    async def attach_csv(
        self,
        owner_id: UUID,
        report_id: UUID,
        content: bytes,
        media_type: str,
        filename: str,
        key: str,
    ) -> tuple[SourceDetail, bool]:
        if report_id != self.report_id:
            raise ResourceNotFound
        parse_csv(
            content,
            max_bytes=self.settings.source_csv_max_bytes,
            max_records=self.settings.source_csv_max_records,
            media_type=media_type,
        )
        if ("csv", key) in self.fingerprints and self.fingerprints[("csv", key)] != content:
            raise IdempotencyConflict
        self.fingerprints[("csv", key)] = content
        self.calls += 1
        self.last_content = content
        return self.detail_model("csv"), self.calls > 1

    async def detail(self, owner_id: UUID, report_id: UUID, source_id: UUID) -> SourceDetail:
        if report_id != self.report_id or source_id != self.source_id:
            raise ResourceNotFound
        return self.detail_model("csv")

    async def preview(
        self, owner_id: UUID, report_id: UUID, source_id: UUID, assets: Any
    ) -> SourcePreview:
        if report_id != self.report_id or source_id != self.source_id:
            raise ResourceNotFound
        if isinstance(self.last_content, str):
            return SourcePreview.model_validate(
                text_preview(
                    self.last_content,
                    max_chars=self.settings.source_preview_max_text_chars,
                    max_response_bytes=self.settings.source_preview_max_response_bytes,
                )
            )
        parsed = parse_csv(
            self.last_content,
            max_bytes=self.settings.source_csv_max_bytes,
            max_records=self.settings.source_csv_max_records,
        )
        return SourcePreview.model_validate(
            csv_preview(
                parsed,
                max_rows=self.settings.source_preview_max_rows,
                max_cell_chars=self.settings.source_preview_max_cell_chars,
                max_response_bytes=self.settings.source_preview_max_response_bytes,
            )
        )


def client_for(settings: Settings, fake: FakeSources) -> TestClient:
    app = create_app(settings, client_factory=lambda _: cast(ResourceClients, FakeClients()))
    app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(
        id=uuid4()
    )
    app.dependency_overrides[services] = lambda: fake
    app.dependency_overrides[get_asset_services] = lambda: object()
    return TestClient(app)


def test_source_runtime_contract_and_openapi(settings: Settings) -> None:
    fake = FakeSources(settings)
    with client_for(settings, fake) as client:
        base = f"/api/v1/reports/{fake.report_id}/sources"
        headers = {"Idempotency-Key": "source-key"}
        text = client.post(base + "/text", json={"content": " 表=1 "}, headers=headers)
        assert text.status_code == 201
        assert text.json()["data"]["byte_size"] == len(" 表=1 ")
        assert "inline_text" not in text.text
        replay = client.post(base + "/text", json={"content": " 表=1 "}, headers=headers)
        assert replay.status_code == 201 and replay.headers["Idempotency-Replayed"] == "true"
        assert (
            client.post(base + "/text", json={"content": "changed"}, headers=headers).status_code
            == 409
        )
        assert (
            client.post(
                base + "/text", json={"content": "x", "object_key": "secret"}, headers=headers
            ).status_code
            == 422
        )
        assert client.post(base + "/text", json={"content": "x"}).status_code == 422
        csv = client.post(
            base + "/csv",
            files={"file": ("../unsafe.csv", b"a,b\n1,2", "text/csv")},
            headers=headers,
        )
        assert csv.status_code == 201
        assert csv.json()["data"]["original_filename_untrusted"] == "../unsafe.csv"
        assert "object_key" not in csv.text
        csv_replay = client.post(
            base + "/csv",
            files={"file": ("../unsafe.csv", b"a,b\n1,2", "text/csv")},
            headers=headers,
        )
        assert csv_replay.status_code == 201
        assert csv_replay.headers["Idempotency-Replayed"] == "true"
        assert (
            client.post(
                base + "/csv",
                files={"file": ("other.csv", b"a,b\n3,4", "text/csv")},
                headers=headers,
            ).status_code
            == 409
        )
        assert (
            client.post(
                base + "/csv",
                files={"file": ("x.csv", b"a,b\n\xff", "text/csv")},
                headers={"Idempotency-Key": "bad-encoding"},
            ).status_code
            == 415
        )
        assert (
            client.post(
                base + "/csv",
                files={"file": ("x.csv", b'a,b\n"bad', "text/csv")},
                headers={"Idempotency-Key": "bad-syntax"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                base + "/csv",
                files={"file": ("x.csv", b"a,b\n1,2", "image/png")},
                headers={"Idempotency-Key": "bad-type"},
            ).status_code
            == 415
        )
        assert client.post(base + "/csv", files={}, headers=headers).status_code == 415
        assert (
            client.post(
                base + "/csv",
                files=[
                    ("file", ("a.csv", b"a,b", "text/csv")),
                    ("file", ("b.csv", b"a,b", "text/csv")),
                ],
                headers=headers,
            ).status_code
            == 400
        )
        assert client.get(base + f"/{fake.source_id}").status_code == 200
        assert client.get(base + f"/{fake.source_id}/preview").json()["data"]["confirmed"] is False
        assert client.get(f"/api/v1/reports/{uuid4()}/sources/{fake.source_id}").status_code == 404
        assert (
            client.post(
                f"/api/v1/reports/{uuid4()}/sources/text", json={"content": "ok"}, headers=headers
            ).status_code
            == 404
        )
        spec = client.get("/openapi.json").json()
        operation = spec["paths"]["/api/v1/reports/{report_id}/sources/csv"]["post"]
        assert "multipart/form-data" in operation["requestBody"]["content"]
        assert "201" in operation["responses"]
        assert "415" in operation["responses"]


def test_csv_upload_byte_limit_and_authentication(settings: Settings) -> None:
    fake = FakeSources(settings.model_copy(update={"source_csv_max_bytes": 4}))
    with client_for(settings, fake) as client:
        base = f"/api/v1/reports/{fake.report_id}/sources/csv"
        response = client.post(
            base,
            files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
            headers={"Idempotency-Key": "limit"},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "payload_too_large"
    app = create_app(settings, client_factory=lambda _: cast(ResourceClients, FakeClients()))
    app.dependency_overrides[services] = lambda: fake
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/reports/{fake.report_id}/sources/csv",
            files={"file": ("x.csv", b"a,b", "text/csv")},
            headers={"Idempotency-Key": "unauth"},
        )
        assert response.status_code == 401


def test_csv_and_text_preview_are_bounded_and_unvalidated(settings: Settings) -> None:
    limited = settings.model_copy(
        update={"source_preview_max_rows": 1, "source_preview_max_text_chars": 3}
    )
    fake = FakeSources(limited)
    with client_for(limited, fake) as client:
        base = f"/api/v1/reports/{fake.report_id}/sources"
        csv = b"date,date\n2026-01-01,A\n2026-01-02,B\n"
        assert (
            client.post(
                base + "/csv",
                files={"file": ("x.csv", csv, "text/csv")},
                headers={"Idempotency-Key": "preview-csv"},
            ).status_code
            == 201
        )
        preview = client.get(base + f"/{fake.source_id}/preview").json()["data"]
        assert preview["columns"] == [
            {"ordinal": 0, "original_header": "date"},
            {"ordinal": 1, "original_header": "date"},
        ]
        assert preview["rows"] == [{"record_index": 1, "values": ["2026-01-01", "A"]}]
        assert preview["total_records"] == 2
        assert preview["truncated"] is True
        assert preview["validation_status"] == "unvalidated"
        assert preview["confirmed"] is False
        assert (
            client.post(
                base + "/text",
                json={"content": "abcdef"},
                headers={"Idempotency-Key": "preview-text"},
            ).status_code
            == 201
        )
        text = client.get(base + f"/{fake.source_id}/preview").json()["data"]
        assert text["excerpt"] == "abc"
        assert text["truncated"] is True
        assert text["validation_status"] == "unvalidated"
