from __future__ import annotations

import asyncio
import logging
import threading
from io import BytesIO
from typing import Any

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError

from app.storage.errors import StorageError, StorageErrorCode
from app.storage.s3 import S3ObjectStorage
from tests.unit.storage.helpers import prepared_csv


def client_error(status: int, code: str, message: str = "provider-secret-message") -> ClientError:
    return ClientError(
        {
            "ResponseMetadata": {"HTTPStatusCode": status},
            "Error": {"Code": code, "Message": message},
        },
        "storage-operation",
    )


class MemoryS3Client:
    def __init__(self) -> None:
        self.object: dict[str, Any] | None = None
        self.thread_ids: list[int] = []
        self.delete_calls = 0
        self.next_error: BaseException | None = None
        self.operation_errors: dict[str, BaseException] = {}

    def _observe(self, operation: str) -> None:
        self.thread_ids.append(threading.get_ident())
        operation_error = self.operation_errors.pop(operation, None)
        if operation_error is not None:
            raise operation_error
        if self.next_error is not None:
            error = self.next_error
            self.next_error = None
            raise error

    def head_object(self, **_: object) -> dict[str, Any]:
        self._observe("head_object")
        if self.object is None:
            raise client_error(404, "NoSuchKey")
        return {key: value for key, value in self.object.items() if key != "Body"}

    def put_object(self, **values: Any) -> dict[str, object]:
        self._observe("put_object")
        if self.object is not None:
            raise client_error(412, "PreconditionFailed")
        body = values["Body"]
        self.object = {
            "Body": body.read(),
            "ContentLength": values["ContentLength"],
            "ContentType": values["ContentType"],
            "Metadata": values["Metadata"],
        }
        assert values["IfNoneMatch"] == "*"
        assert "ACL" not in values
        return {}

    def get_object(self, **_: object) -> dict[str, Any]:
        self._observe("get_object")
        if self.object is None:
            raise client_error(404, "NoSuchKey")
        return {**self.object, "Body": BytesIO(self.object["Body"])}

    def delete_object(self, **_: object) -> dict[str, object]:
        self._observe("delete_object")
        self.delete_calls += 1
        self.object = None
        return {}


@pytest.mark.asyncio
async def test_s3_adapter_conditional_round_trip_and_thread_offload() -> None:
    main_thread = threading.get_ident()
    client = MemoryS3Client()
    adapter = S3ObjectStorage(client, correlation_id_factory=lambda: "correlation")
    prepared = await prepared_csv()
    try:
        assert await adapter.head(prepared.metadata.identity) is None
        assert await adapter.put_if_absent(prepared) is True
        assert await adapter.put_if_absent(prepared) is False
        assert await adapter.head(prepared.metadata.identity) == prepared.metadata
        fetched = await adapter.get(prepared.metadata.identity)
        assert fetched.body.read() == b"date,campaign_name\n2026-01-01,A\n"
        fetched.body.close()
        assert client.thread_ids and all(value != main_thread for value in client.thread_ids)
        assert await adapter.delete_exact(prepared.metadata, created_by_invocation=False) is False
        assert await adapter.delete_exact(prepared.metadata, created_by_invocation=True) is True
        assert client.delete_calls == 1
    finally:
        prepared.close()


@pytest.mark.asyncio
async def test_s3_adapter_normalizes_timeout_forbidden_and_malformed_response() -> None:
    client = MemoryS3Client()
    adapter = S3ObjectStorage(client)
    prepared = await prepared_csv()
    try:
        client.next_error = ConnectTimeoutError(endpoint_url="https://sentinel.invalid")
        with pytest.raises(StorageError) as timeout:
            await adapter.head(prepared.metadata.identity)
        assert timeout.value.code is StorageErrorCode.TIMEOUT

        client.next_error = client_error(403, "AccessDenied")
        with pytest.raises(StorageError) as forbidden:
            await adapter.head(prepared.metadata.identity)
        assert forbidden.value.code is StorageErrorCode.FORBIDDEN

        client.object = {
            "Body": b"bad",
            "ContentLength": 3,
            "ContentType": "text/csv",
            "Metadata": {},
        }
        with pytest.raises(StorageError) as malformed:
            await adapter.get(prepared.metadata.identity)
        assert malformed.value.code is StorageErrorCode.INTEGRITY_FAILED
    finally:
        prepared.close()


@pytest.mark.asyncio
async def test_s3_adapter_propagates_cancellation_without_converting_it() -> None:
    client = MemoryS3Client()
    adapter = S3ObjectStorage(client)
    prepared = await prepared_csv()
    client.operation_errors["head_object"] = asyncio.CancelledError()
    try:
        with pytest.raises(asyncio.CancelledError):
            await adapter.head(prepared.metadata.identity)
    finally:
        prepared.close()


@pytest.mark.parametrize(
    ("operation", "client_operation"),
    [
        ("put_if_absent", "put_object"),
        ("head", "head_object"),
        ("get", "get_object"),
        ("delete_exact", "delete_object"),
    ],
)
@pytest.mark.asyncio
async def test_every_storage_operation_redacts_sensitive_provider_values(
    caplog: pytest.LogCaptureFixture,
    operation: str,
    client_operation: str,
) -> None:
    forbidden = [
        "sentinel-access-key",
        "https://secret-endpoint.invalid",
        "private-bucket",
        "owners/private/key.csv",
        "raw-original.csv",
        "provider-secret-message",
        "customer-bytes",
    ]
    client = MemoryS3Client()
    adapter = S3ObjectStorage(client, correlation_id_factory=lambda: "safe-correlation")
    prepared = await prepared_csv()
    try:
        if operation == "delete_exact":
            assert await adapter.put_if_absent(prepared)
            caplog.clear()
        client.operation_errors[client_operation] = client_error(
            500,
            "InternalError",
            " | ".join(forbidden),
        )
        with caplog.at_level(logging.INFO, logger="app.storage"):
            with pytest.raises(StorageError) as error:
                if operation == "put_if_absent":
                    await adapter.put_if_absent(prepared)
                elif operation == "head":
                    await adapter.head(prepared.metadata.identity)
                elif operation == "get":
                    await adapter.get(prepared.metadata.identity)
                else:
                    await adapter.delete_exact(
                        prepared.metadata,
                        created_by_invocation=True,
                    )
        observed = f"{error.value}\n{caplog.text}"
        assert "correlation_id=safe-correlation" in observed
        assert f"operation={operation}" in observed
        assert "outcome=storage_unavailable" in observed
        for value in forbidden:
            assert value not in observed
    finally:
        prepared.close()
