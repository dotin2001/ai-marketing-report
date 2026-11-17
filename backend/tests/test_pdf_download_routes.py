from __future__ import annotations

import asyncio
from tempfile import SpooledTemporaryFile
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    AuthenticatedPrincipal,
    get_asset_services,
    get_authenticated_principal,
)
from app.api.pdf_downloads import _stream_verified
from app.core.config import Settings
from app.core.resources import ResourceClients
from app.domain.assets import ExportNotReady, ResourceNotFound
from app.main import create_app
from app.storage.errors import StorageError, StorageErrorCode
from app.storage.files import VerifiedContent
from tests.unit.storage.helpers import prepared_pdf


class FakeClients:
    object_storage = object()

    async def close(self) -> None:
        return None


class FakeAssetServices:
    def __init__(self, result: VerifiedContent | BaseException) -> None:
        self.result = result
        self.calls = 0

    async def retrieve_pdf(self, **_: Any) -> VerifiedContent:
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def client_with(
    settings: Settings,
    service: FakeAssetServices,
    *,
    authenticated: bool = True,
) -> TestClient:
    app = create_app(
        settings,
        client_factory=lambda _: cast(ResourceClients, FakeClients()),
    )
    app.dependency_overrides[get_asset_services] = lambda: service
    if authenticated:
        app.dependency_overrides[get_authenticated_principal] = lambda: AuthenticatedPrincipal(
            id=UUID("11111111-1111-1111-1111-111111111111")
        )
    return TestClient(app)


def path() -> str:
    return f"/api/v1/reports/{uuid4()}/versions/{uuid4()}/pdf-exports/{uuid4()}/download"


def test_unauthenticated_download_uses_safe_standard_envelope(settings: Settings) -> None:
    service = FakeAssetServices(ResourceNotFound())
    with client_with(settings, service, authenticated=False) as client:
        response = client.get(path(), headers={"X-Request-ID": "request-1"})
    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "unauthenticated",
            "message": "Authentication is required.",
            "request_id": "request-1",
            "retryable": False,
            "details": [],
            "context": {},
        }
    }
    assert service.calls == 0


@pytest.mark.parametrize("foreign_or_missing", ["missing", "foreign"])
def test_missing_and_cross_owner_are_indistinguishable_without_bytes(
    settings: Settings, foreign_or_missing: str
) -> None:
    service = FakeAssetServices(ResourceNotFound(foreign_or_missing))
    with client_with(settings, service) as client:
        response = client.get(path(), headers={"X-Request-ID": "same-request"})
    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "resource_not_found",
        "message": "The requested PDF export was not found.",
        "request_id": "same-request",
        "retryable": False,
        "details": [],
        "context": {"resource_type": "pdf_export"},
    }
    assert response.content.startswith(b'{"error"')


@pytest.mark.parametrize(
    ("state", "retryable"),
    [("queued", True), ("running", True), ("failed", False)],
)
def test_incomplete_exports_return_409_without_file_bytes(
    settings: Settings, state: str, retryable: bool
) -> None:
    service = FakeAssetServices(ExportNotReady(state))
    with client_with(settings, service) as client:
        response = client.get(path())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "export_not_ready"
    assert response.json()["error"]["retryable"] is retryable
    assert response.json()["error"]["context"] == {"state": state}
    assert response.headers.get("content-type", "").startswith("application/json")


@pytest.mark.parametrize(
    ("code", "status", "public_code"),
    [
        (StorageErrorCode.INTEGRITY_FAILED, 500, "internal_error"),
        (StorageErrorCode.TIMEOUT, 503, "dependency_unavailable"),
        (StorageErrorCode.UNAVAILABLE, 503, "dependency_unavailable"),
    ],
)
def test_storage_failures_map_to_sanitized_errors(
    settings: Settings,
    code: StorageErrorCode,
    status: int,
    public_code: str,
) -> None:
    service = FakeAssetServices(StorageError(code))
    with client_with(settings, service) as client:
        response = client.get(path())
    assert response.status_code == status
    assert response.json()["error"]["code"] == public_code
    assert "object" not in response.text.lower()


@pytest.mark.asyncio
async def test_succeeded_pdf_is_exact_and_uses_safe_headers_and_cleanup(
    settings: Settings,
) -> None:
    prepared = await prepared_pdf(b"%PDF-1.7\nexact\x00bytes")
    temporary: SpooledTemporaryFile[bytes] = SpooledTemporaryFile(mode="w+b")
    temporary.write(b"%PDF-1.7\nexact\x00bytes")
    temporary.seek(0)
    verified = VerifiedContent(
        metadata=prepared.metadata,
        safe_filename="../../B\u00e1o c\u00e1o\r\nInjected: yes.pdf",
        file=temporary,
    )
    service = FakeAssetServices(verified)
    with client_with(settings, service) as client:
        response = client.get(path())
    assert response.status_code == 200
    assert response.content == b"%PDF-1.7\nexact\x00bytes"
    assert response.headers["content-length"] == str(len(response.content))
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert "../" not in disposition and "\r" not in disposition and "\n" not in disposition
    assert temporary.closed
    prepared.close()


@pytest.mark.parametrize("termination", ["disconnect", "cancellation"])
@pytest.mark.asyncio
async def test_stream_cleanup_on_disconnect_or_cancellation(termination: str) -> None:
    prepared = await prepared_pdf(b"x")
    temporary: SpooledTemporaryFile[bytes] = SpooledTemporaryFile(mode="w+b")
    temporary.write(b"x" * (64 * 1024 + 1))
    temporary.seek(0)
    verified = VerifiedContent(
        metadata=prepared.metadata,
        safe_filename="report.pdf",
        file=temporary,
    )
    stream = _stream_verified(verified)
    assert len(next(stream)) == 64 * 1024
    if termination == "disconnect":
        stream.close()
    else:
        with pytest.raises(asyncio.CancelledError):
            stream.throw(asyncio.CancelledError())
    assert temporary.closed
    prepared.close()
