"""S3-compatible implementation using one lifespan-owned boto3 client."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, BinaryIO, cast
from uuid import UUID, uuid4

import anyio
from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    ReadTimeoutError,
)

from app.storage.errors import StorageError, StorageErrorCode
from app.storage.files import PreparedContent
from app.storage.telemetry import instrument_storage
from app.storage.types import ObjectIdentity, ObjectMetadata, ProviderObject


def _client_status(error: ClientError) -> tuple[int, str]:
    response = cast(dict[str, Any], error.response)
    metadata = cast(dict[str, Any], response.get("ResponseMetadata", {}))
    details = cast(dict[str, Any], response.get("Error", {}))
    return int(metadata.get("HTTPStatusCode", 0)), str(details.get("Code", ""))


def _raise_sanitized(error: BaseException) -> None:
    if isinstance(error, (ConnectTimeoutError, ReadTimeoutError, TimeoutError)):
        raise StorageError(StorageErrorCode.TIMEOUT) from None
    if isinstance(error, ClientError):
        status, _ = _client_status(error)
        if status in {401, 403}:
            raise StorageError(StorageErrorCode.FORBIDDEN) from None
    raise StorageError(StorageErrorCode.UNAVAILABLE) from None


def _parse_metadata(
    identity: ObjectIdentity,
    *,
    provider_metadata: Mapping[str, str],
    content_type: object,
    content_length: object,
) -> ObjectMetadata:
    try:
        if provider_metadata["schema-version"] != "1":
            raise ValueError
        if provider_metadata["environment"] != identity.environment:
            raise ValueError
        if provider_metadata["purpose"] != identity.purpose.value:
            raise ValueError
        size = int(provider_metadata["byte-size"])
        if not isinstance(content_length, (int, str)):
            raise ValueError
        response_size = int(content_length)
        response_type = str(content_type)
        if size != response_size or provider_metadata["content-type"] != response_type:
            raise ValueError
        checksum = provider_metadata["sha256"]
        if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
            raise ValueError
        return ObjectMetadata(
            identity=identity,
            owner_id=UUID(provider_metadata["owner-id"]),
            report_id=UUID(provider_metadata["report-id"]),
            logical_id=UUID(provider_metadata["logical-id"]),
            content_type=response_type,
            byte_size=size,
            checksum_sha256=checksum,
        )
    except (KeyError, TypeError, ValueError):
        raise StorageError(StorageErrorCode.INTEGRITY_FAILED) from None


class S3ObjectStorage:
    """Provider adapter that never accepts caller-selected keys or ACLs."""

    def __init__(
        self,
        client: Any,
        *,
        correlation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._client = client
        self._correlation_id_factory = correlation_id_factory or (lambda: str(uuid4()))

    async def put_if_absent(self, prepared: PreparedContent) -> bool:
        metadata = prepared.metadata
        with instrument_storage(
            operation="put_if_absent",
            purpose=metadata.identity.purpose,
            correlation_id=self._correlation_id_factory(),
        ):

            def put() -> None:
                prepared.file.seek(0)
                self._client.put_object(
                    Bucket=metadata.identity.bucket,
                    Key=metadata.identity.key,
                    Body=prepared.file,
                    ContentLength=metadata.byte_size,
                    ContentType=metadata.content_type,
                    Metadata=metadata.provider_metadata(),
                    IfNoneMatch="*",
                )

            try:
                await anyio.to_thread.run_sync(put)
                return True
            except ClientError as error:
                status, code = _client_status(error)
                if status in {409, 412} or code in {
                    "ConditionalRequestConflict",
                    "PreconditionFailed",
                }:
                    return False
                _raise_sanitized(error)
            except (BotoCoreError, TimeoutError) as error:
                _raise_sanitized(error)
        raise AssertionError("unreachable")

    async def head(self, identity: ObjectIdentity) -> ObjectMetadata | None:
        with instrument_storage(
            operation="head",
            purpose=identity.purpose,
            correlation_id=self._correlation_id_factory(),
        ):
            try:
                response = await anyio.to_thread.run_sync(
                    lambda: self._client.head_object(Bucket=identity.bucket, Key=identity.key)
                )
            except ClientError as error:
                status, code = _client_status(error)
                if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
                    return None
                _raise_sanitized(error)
            except (BotoCoreError, TimeoutError) as error:
                _raise_sanitized(error)
            if not isinstance(response, dict):
                raise StorageError(StorageErrorCode.INTEGRITY_FAILED)
            return _parse_metadata(
                identity,
                provider_metadata=cast(Mapping[str, str], response.get("Metadata", {})),
                content_type=response.get("ContentType"),
                content_length=response.get("ContentLength"),
            )

    async def get(self, identity: ObjectIdentity) -> ProviderObject:
        with instrument_storage(
            operation="get",
            purpose=identity.purpose,
            correlation_id=self._correlation_id_factory(),
        ):
            try:
                response = await anyio.to_thread.run_sync(
                    lambda: self._client.get_object(Bucket=identity.bucket, Key=identity.key)
                )
            except (BotoCoreError, ClientError, TimeoutError) as error:
                _raise_sanitized(error)
            if not isinstance(response, dict) or not hasattr(response.get("Body"), "read"):
                body = response.get("Body") if isinstance(response, dict) else None
                closer = getattr(body, "close", None)
                if callable(closer):
                    await anyio.to_thread.run_sync(closer)
                raise StorageError(StorageErrorCode.INTEGRITY_FAILED)
            body = cast(BinaryIO, response["Body"])
            try:
                metadata = _parse_metadata(
                    identity,
                    provider_metadata=cast(Mapping[str, str], response.get("Metadata", {})),
                    content_type=response.get("ContentType"),
                    content_length=response.get("ContentLength"),
                )
            except BaseException:
                await anyio.to_thread.run_sync(body.close)
                raise
            return ProviderObject(metadata=metadata, body=body)

    async def delete_exact(
        self,
        expected: ObjectMetadata,
        *,
        created_by_invocation: bool,
    ) -> bool:
        with instrument_storage(
            operation="delete_exact",
            purpose=expected.identity.purpose,
            correlation_id=self._correlation_id_factory(),
        ):
            if not created_by_invocation:
                return False
            actual = await self.head(expected.identity)
            if actual is None or actual != expected:
                return False
            try:
                await anyio.to_thread.run_sync(
                    lambda: self._client.delete_object(
                        Bucket=expected.identity.bucket,
                        Key=expected.identity.key,
                    )
                )
                return True
            except (BotoCoreError, ClientError, TimeoutError) as error:
                _raise_sanitized(error)
        raise AssertionError("unreachable")
